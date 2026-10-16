# Scribe examples

| Folder | What it holds | Status |
|---|---|---|
| `*.scribe` (this folder) | Programs for the language as it exists today (v0.1). Each has a recorded run in `tests/test_end_to_end.py`. | works |
| `errors/` | Programs the compiler rejects today. Line 1 is `# expect: <text>`, the text the error message must contain. | works |
| `future/` | **Proposed** syntax for later versions: typed scalars, functions, overloading, unions, arrays, classes, iterators. | rejected today |
| `future/errors/` | Programs the *future* compiler must reject, with the diagnostic we want. | rejected today |

Try them:

```sh
python -m scribe_lang.cli examples/primes.scribe -o build/primes.c
cc -std=c11 -o build/primes build/primes.c && echo 30 | build/primes
```

Highlights of v0.1: `primes.scribe` (nested loops, `goto` as break) and
`newton_sqrt.scribe` (float math, early exit, block-scoped temporaries).

`tests/test_example_folders.py` checks that every `errors/` file fails with its
promised message and that every `future/` file is still rejected. When a
feature ships, move its example up a level and record its run.
The `future/` syntax is a design sketch, not a commitment; the reasoning is in
[`docs/whitepaper.md`](../docs/whitepaper.md).
