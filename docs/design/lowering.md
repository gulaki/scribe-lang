# Lowering and templates (proposal)

## Stages

```
AST -> typed AST -> typed IR (explicit checks, moves, cleanups)
    -> monomorphised IR -> C AST -> C text with #line
```
Each stage is a pure function over a data structure, printable for tests. Today's compiler goes `AST -> C text`; the IR is the first step to add (target: v0.2), because checked arithmetic is the first feature that needs a lowering decision.

## Naming

All generated names are deterministic and readable.

| Scribe | C |
|---|---|
| variable `x` | `v_x` (`v_x_1` when shadowed in nested scope) |
| label `top` | `l_top` |
| function `gcd(int,int)` | `f_gcd__int_int` |
| overload `describe(float)` | `f_describe__float` |
| method `Account.deposit` | `m_Account__deposit` |
| generic `sum_all[int]` | `f_sum_all__int` |
| type `Array[int]` | `Array__int`, ops `Array__int__push` |
| temporaries | `t_1`, `t_2`, ... per function |
| cleanup labels | `c_1`, `c_2`, ... |

Prefix letters keep namespaces disjoint (a variable and a function with the same Scribe name never collide). Mangling must be injective; add a test that lowers a corpus and asserts no two Scribe entities share a C name. Emit `#line` so compiler errors and debuggers show Scribe positions.

## Runtime templates

Hand-written, reviewed C stored as template files with a deliberately tiny substitution language:

```c
// templates/array.c.in
typedef struct { @T@ *data; int64_t len, cap; } @Array@;
static inline @T@ @Array@__get(const @Array@ *a, int64_t i) {
    if ((uint64_t)i >= (uint64_t)a->len) scribe_trap_index(i, a->len);
    return a->data[i];
}
```
- Placeholders: `@T@` (element type), `@Array@` (mangled name), `@SIZE@`, nothing else. No logic, no loops.
- The instantiator checks that every placeholder is bound and that no `@` remains.
- A template is instantiated once per element type per program, into a single generated header section, in dependency order.
- The template set is the **trusted base**: reviewed line by line, built under sanitisers, differential-tested against a reference model.

## Monomorphisation

User generics are instantiated in the IR: collect reachable `(function, type-args)` pairs from `main`, clone and substitute, name via the table above, deduplicate. Errors are reported against the generic definition (constraints are checked once, not per instantiation). Recursion in instantiation (`f[T]` calling `f[Array[T]]`) gets a depth limit and an error.

## Shape of emitted code

```c
static int64_t f_gcd__int_int(int64_t v_a, int64_t v_b) {
    while (v_b != 0) { ...checked ops via helpers... }
    return v_a;
}
```
Rules: one statement per line; locals declared and zero-initialised at the top of their block; `static` for everything except `main`; checked arithmetic through small `static inline` helpers so the generated code stays readable; no macros in generated code.

## Build

The CLI keeps writing Makefile/Ninja files next to the C output (paths relative to the build file). Add `--sanitize` to build with UBSan/ASan, used by CI.
