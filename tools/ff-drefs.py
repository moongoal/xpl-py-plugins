#!/usr/bin/env python3
"""Produce statemanager.csv file from Flight Factor dataref list."""

with open('datarefs.txt') as f, open('statemanager.csv', 'w') as fo:
    for line in f:
        name, desc = line.split(' ', 1)

        if 'switch' in desc:
            type_ = 'int'
        elif 'knob' in desc:
            type_ = 'float'
        elif 'click button' in desc:
            continue # skip
        else:
            raise ValueError('Unknown dataref type', line)

        print(f'{name},{type_}', file=fo)
