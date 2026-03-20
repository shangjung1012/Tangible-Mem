#!/bin/bash

for i in $(seq -f "%03g" 1 31)
do
    wget "https://groups.inf.ed.ac.uk/ami/ICSIsignals/NXT/Bmr${i}.interaction.wav"
done