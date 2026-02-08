# IcePanel Diagram or Flow to Mermaid Sequence

## Forked from chaoslabs-bg/icepanel-sequence-diagrams

It looks like IcePanel modified their API at some point (without bumping the version) which broke the original code. 
This version works as of Feb 2026.

Now with added full diagram support!


## Overview

This is a CLI tool that converts [IcePanel](https://icepanel.io/) diagrams and flows to [Mermaid](https://mermaid-js.github.io/mermaid/#/) sequence diagram. 

## Usage

### Install

To install locally, run:

```shell
git clone https://github.com/chaoslabs-bg/icepanel-sequence-diagrams.git
cd icepanel-sequence-diagrams
# Optional ####
# create virtual environment
python3 -m venv venv
# /Optional ####
pip install -r requirements.txt
```

### Usage

```shell
export API_KEY=<your-icepanel-api-key>
export LANDSCAPE_ID=<your-landscape-id>
export LANDSCAPE_VERSION = 'latest'
export MMDC_CMD=/path/to/mmdc #optional only if you want to convert the .mmd to .png
python main.py --flow-name="Name of my flow"
python main.py --diagram-name"Name of my diagram"
```

## License

MIT License

## Support 

See [the original repo](https://github.com/chaoslabs-bg/icepanel-sequence-diagrams?tab=readme-ov-file#support)

