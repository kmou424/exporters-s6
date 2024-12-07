import os
import tomllib
from dataclasses import dataclass, is_dataclass, fields
from typing import Type, Any


@dataclass
class DeployConfig:
    listen_host: str
    root_dir: str
    exporter_dir: str
    log_file: str


@dataclass
class ServiceConfig:
    name: str
    version: str
    dist_url: str
    post_download: str
    install_bin: str
    args: str


@dataclass
class Config:
    deploy: DeployConfig
    exporters: list[ServiceConfig]


def from_dict(data: dict, cls: Type) -> Any:
    if not is_dataclass(cls):
        raise TypeError(f"{cls} is not a dataclass")

    field_values = {}
    # noinspection PyDataclass,PyTypeChecker
    for field in fields(cls):
        field_name = field.name
        field_type = field.type

        if field_name not in data:
            raise ValueError(f"param data missing field '{field_name}'")

        value = data[field_name]
        if is_dataclass(field_type):
            field_values[field_name] = from_dict(value, field_type)
        elif isinstance(value, list):
            # noinspection PyUnresolvedReferences
            if hasattr(field_type, '__origin__') and field_type.__origin__ is list:
                # noinspection PyUnresolvedReferences
                item_type = field_type.__args__[0]
                if not is_dataclass(item_type):
                    raise TypeError(f"{item_type} is not a dataclass")
                field_values[field_name] = [from_dict(item, item_type) for item in value]
            else:
                # noinspection PyCallingNonCallable
                # it's a type converter, not a function calling
                field_values[field_name] = [field_type(i) for i in value]
        else:
            # noinspection PyCallingNonCallable
            # it's a type converter, not a function calling
            field_values[field_name] = field_type(value)

    return cls(**field_values)


config: Config
required_executables = ['wget', 'execlineb', 's6-svscan']


class utils:
    @staticmethod
    def to_abs_path(path: str) -> str:
        return os.path.abspath(os.path.expanduser(path))

    @staticmethod
    def run_cmd(cmd: str, cwd: str = None, output_on_error: bool = True) -> bool:
        import subprocess
        try:
            subprocess.run(cmd, cwd=cwd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except subprocess.CalledProcessError as e:
            if output_on_error:
                print(f'Error: {e.output.decode()}')
            else:
                print(f'Error: {e}')
            return False

    @staticmethod
    def check_dict(data: dict, keys: list[str]):
        for key in keys:
            if key not in data:
                raise KeyError(f'{key} not found in config')

    @staticmethod
    def logging(*args, exporter: str = None):
        if exporter:
            print(f'\t[{exporter}]', *args)
        else:
            print(*args)


class safe:
    @staticmethod
    def make_dirs(path: str):
        if not os.path.exists(path):
            os.makedirs(path)

    @staticmethod
    def check_executables(executables: list[str]):
        for executable in executables:
            if not utils.run_cmd(f'which {executable}', output_on_error=False):
                raise FileNotFoundError(f'{executable} not found')


class VarsFormatter:
    __vars: dict[str, str]

    def __init__(self, exporter: ServiceConfig):
        self.__vars = {
            # main variables
            'ROOT_DIR': config.deploy.root_dir,
            'LISTEN_HOST': config.deploy.listen_host,
            # exporter variables
            'NAME': exporter.name,
            'VERSION': exporter.version,
        }
        self.add_var('EXPORTER_DIR', self.format(config.deploy.exporter_dir))

    def add_var(self, name: str, value: str):
        self.__vars[name] = value

    def format(self, text: str) -> str:
        for name, value in self.__vars.items():
            # format {{name}} to value
            text = text.replace('{{' + name + '}}', value)
        return text


def parse_config():
    if not os.path.exists('deploy.toml'):
        raise FileNotFoundError('deploy.toml not found')
    with open('deploy.toml', 'r') as f:
        global config
        config = from_dict(tomllib.loads(f.read()), Config)


def postprocess_config():
    config.deploy.root_dir = utils.to_abs_path(config.deploy.root_dir)
    config.deploy.exporter_dir = utils.to_abs_path(os.path.join(config.deploy.root_dir, config.deploy.exporter_dir))
    config.deploy.log_file = utils.to_abs_path(os.path.join(config.deploy.exporter_dir, config.deploy.log_file))

    safe.make_dirs(config.deploy.root_dir)


def deploy_exporter(exporter: ServiceConfig, formatter: VarsFormatter):
    exporter_dir = formatter.format(config.deploy.exporter_dir)
    log_file = formatter.format(config.deploy.log_file)
    tmp_dir = os.path.join(exporter_dir, 'tmp')

    safe.make_dirs(exporter_dir)
    safe.make_dirs(tmp_dir)

    # download dist package
    dist_url = formatter.format(exporter.dist_url)
    dist_file = os.path.join(tmp_dir, os.path.basename(dist_url))
    formatter.add_var('DIST_FILE', dist_file)
    utils.logging(f'Downloading package {dist_file}...', exporter=exporter.name)
    utils.run_cmd(f'wget -O {dist_file} {dist_url}')

    # run post download script
    if exporter.post_download != '':
        post_download = formatter.format(exporter.post_download)
        utils.logging(f'Running post download script...', exporter=exporter.name)
        utils.run_cmd(formatter.format(post_download), cwd=tmp_dir)

    install_bin = os.path.join(tmp_dir, formatter.format(exporter.install_bin))
    if not os.path.exists(install_bin):
        raise FileNotFoundError(f'install_bin "{exporter.install_bin}" not found')

    target_bin_file = os.path.join(exporter_dir, exporter.name)
    # move install_bin to bin_file
    utils.run_cmd(f'mv {install_bin} {target_bin_file}')

    # fix permission
    utils.logging(f'Fixing permission...', exporter=exporter.name)
    if os.path.exists(target_bin_file):
        utils.run_cmd(f'chmod +x {target_bin_file}')

    # generate s6 run file
    utils.logging(f'Generating s6 run file...', exporter=exporter.name)
    run_file = os.path.join(exporter_dir, 'run')
    with open(run_file, 'w') as f:
        f.write(f'''#!/bin/execlineb -P
redirfd -a 1 {log_file}
redirfd -a 2 {log_file}
{target_bin_file} {formatter.format(exporter.args)}
''')
    utils.run_cmd(f'chmod +x {run_file}')

    # clean up tmp dir
    utils.logging(f'Cleaning up...', exporter=exporter.name)
    utils.run_cmd(f'rm -rf {tmp_dir}')


def init():
    safe.check_executables(required_executables)
    parse_config()
    postprocess_config()


def main():
    for idx, exporter in enumerate(config.exporters):
        utils.logging(f'Deploying {exporter.name}...')
        deploy_exporter(exporter, VarsFormatter(exporter))
        if idx != len(config.exporters) - 1:
            print()


if __name__ == '__main__':
    init()
    main()
