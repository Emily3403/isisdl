These benchmarks were conducted on a dedicated V-Server with Gigabit internet. Only two courses we downloaded for a
total of 2.8 GiB.

A total of 207 files were downloaded with 73 `.mp4` files. For each category 3 tests were conducted with the strategy
round-robin i.e.

```
Threads 1 (Test 1) → Threads 3 (Test 1) → … → Threads 1 (Test 2) → …
```

### isia-tub

This is currently untested aside from my local machine (V-Server is lacking storage).

The result was ~11min for `isisdl` and ~15min for `isia-tub`

### isisdl version 0.1

```

```


### isisdl version 0.2
```
~ No previous downloads ~
#Threads = 1
49s | 52s | 

#Threads = 2
33s | 32s | 

#Threads = 3
28s | 26s | 

#Threads = 5
27s | 25s | 

#Threads = 10
27s |  | 

```