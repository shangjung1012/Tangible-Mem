#!/bin/bash

for i in $(seq -f "%03g" 1 31)
do
    file="Bmr${i}.interaction.wav"
    url="https://groups.inf.ed.ac.uk/ami/ICSIsignals/NXT/${file}"

    echo "Downloading ${file}"
    if ! wget -O "${file}" "${url}"; then
        rm -f "${file}"
        echo "Skipping ${file}"
    fi
done
