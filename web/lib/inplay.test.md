# In-Play Probability Sanity Checks

All scenarios use:

- `pHome=0.52`, `pDraw=0.25`, `pAway=0.23`
- `xgHome=1.7`, `xgAway=1.1`
- `totalMinutes=90`

Computed with `env -u NODE_OPTIONS npm_config_cache=/tmp/npm-cache npx tsx ./.inplay-sanity.ts`.

| Scenario | Score/minute | Home | Draw | Away | Check |
| --- | ---: | ---: | ---: | ---: | --- |
| (a) Kickoff reproduces prior | 0-0, 0' | 0.520000000000 | 0.250000000000 | 0.230000000000 | matches input prior |
| (b) Late home lead | 1-0, 85' | 0.943540222768 | 0.054967612248 | 0.001492164984 | home much greater than 0.52 prior |
| (c) Late scoreless draw | 0-0, 88' | 0.036970030728 | 0.941712127421 | 0.021317841851 | draw dominant |
| (d) Away up two after 60' | 0-2, 60' | 0.014930119316 | 0.071286589949 | 0.913783290735 | away dominant |
| (e) Probability sums | above cases | 1.000000000000 | 1.000000000000 | 1.000000000000 | all sums within 1e-9 (`1`, `0.9999999999999999`, `1`, `1`) |
