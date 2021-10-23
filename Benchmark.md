These benchmarks were conducted on a dedicated V-Server with Gigabit internet. Only two courses we downloaded for a
total of 2.8 GiB.

A total of 207 files were downloaded with 73 `.mp4` files. For each category 3 tests were conducted with the strategy
round-robin i.e.

```
Threads 1 (Test 1) → Threads 3 (Test 1) → … → Threads 1 (Test 2) → …
```

### isia-tub

This is currently untested aside from my local machine (V-Server is lacking storage).

The result was ~11min for `isis_dl` and ~15min for `isia-tub`

### isis_dl version 0.1

```
~ No previous downloads ~

#Threads = 1
44s | 52s | 58s ≈ 51.33s

#Threads = 3
29s | 25s | 26s ≈ 26.67s

#Threads = 5
21s | 21s | 21s ≈ 21.00s

#Threads = 10
22s | 21s | 20s ≈ 21.00s


~ Randomly deleted 50% of files ~


~ All files existant ~

#Threads = 1
34s | 33s | 33s ≈ 33.33s

#Threads = 3
17s | 18s | 19s ≈ 18.00s

#Threads = 5
15s | 15s | 16s ≈ 15.33s

#Threads = 10
14s | 13s | 13s ≈ 13.33s
```
