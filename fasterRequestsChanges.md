Ajax server can handle *multiple* requests at once. Neat!


Current timings of some isisdl versions (tested on python3.10):

1.3.7: [7.68, 7.44, 7.64, 7.82, 6.99] → 7.514
1.3.6: [7.02, 7.18, 7.42, 6.99, 7.12] → 7.145
1.3.5: [7.08, 7.75, 7.28, 7.12, 6.93] → 7.231

Now we introduce faster_requests:

faster_requests_v1: [5.77, 6.71, 6.79, 6.10, 6.56, 6.78, 7.04, 6.64] → 6.549
faster_requests_v2: [6.42, 6.23, 6.38, 6.30, 6.71] → 6.407
faster_requests_v3: [] →


Interestingly enough different python version yield different speed.

This is a comparison between them:

python 3.8:  [7.87, 7.02, 6.91, 7.07, 7.29] → 7.232
python 3.9:  [6.70, 6.66, 7.06, 6.72, 6.68] → 6.764
python 3.10: [6.71, 6.05, 5.89, 6.16, 6.56] → 6.273
  → with optimizations: [6.98, 6.64, 6.33, 6.88, 7.02] →
python 3.11: [6.34, 6.49, 6.04, 6.02, 6.42] → 6.262

static version:
python 3.8:  [6.91, 7.03, 7.16, 7.43, 7.36] → 7.178
python 3.10: [7.11, 7.10, 7.32, 7.04, 7.01] → 7.116
 (clang)     [] →


