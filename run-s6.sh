#!/usr/bin/bash

dir=$(dirname "$0")
cd "$dir" || exit

if [ -z "$1" ]; then
    echo "Please provide a directory name as an argument."
    exit 1
fi

if [ ! -d "$1" ]; then
    echo "Directory $1 does not exist."
    exit 1
fi

s6-svscan "$1"