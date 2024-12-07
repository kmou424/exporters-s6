# exporters-s6

A lightweight Python script designed to deploy Prometheus exporters for scraping metrics from various sources. All
exporters are managed using s6 for easier management and control.

## Step-by-Step Guide

1. Clone the repository:
   ```shell
   git clone <repository-url>
   ```
2. Edit the `deploy.toml` file to include the exporters you wish to deploy:
   ```shell
   vim ./deploy.toml
   ```
3. Run the deployment script:
   ```shell
   python3 deploy.py
   ```
4. Start s6 using the path where the generated s6 configurations are stored:
   ```shell
   s6-svscan {the value of deploy.root_dir in deploy.toml}
   ```