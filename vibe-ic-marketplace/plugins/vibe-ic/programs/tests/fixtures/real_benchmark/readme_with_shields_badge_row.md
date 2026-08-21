# Generic Open-Source IC Project

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)  [![User CI](https://github.com/exampleorg/examplerepo/actions/workflows/user_project_ci.yml/badge.svg)](https://github.com/exampleorg/examplerepo/actions/workflows/user_project_ci.yml)  [![Documentation](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://docs.example.org/)  [![Contributors](https://img.shields.io/github/contributors/exampleorg/examplerepo.svg)](https://github.com/exampleorg/examplerepo/graphs/contributors)

A reference open-source design demonstrating the typical badge-row
header pattern found in Caravel / OpenROAD / LibreLane templates and
hundreds of other public IC project READMEs.

## Performance

| Metric    | Value | Unit |
|-----------|-------|------|
| fmax      | 100   | MHz  |
| latency   | 10    | cyc  |

## Features

- 32-bit data path
- Wishbone B4 slave interface
- Configurable register file depth

## Register Map

| Address | Name      | Access | Description       |
|---------|-----------|--------|-------------------|
| 0x00    | CTRL      | RW     | Control register  |
| 0x04    | STATUS    | R      | Status flags      |
| 0x08    | DATA      | RW     | Data port         |
