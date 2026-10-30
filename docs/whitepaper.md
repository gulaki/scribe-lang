# Scribe: a safe, readable front end for C

*Design whitepaper, draft 4. The language today has the scalar types i64, f64, f32 and bool, declarations, chained and multiple assignment, `/` `//` `%` `**`, `and`/`or`/`not`, comparison chains, blocks, `if`/`while`, `break`/`continue` with named loops, and the deprecated `goto`; [`language.md`](language.md) describes it. Everything else here is a design target.*

## 1. Thesis

Scribe is a small language whose compiler emits C. Humans and AI models write Scribe because it is easy to read, easy to generate and hard to get wrong. C stays the target because it is portable, fast and everywhere. The compiler's job is to **own the hard parts of C**: undefined behaviour, memory management, name hygiene and boilerplate. Programs that compile must not exhibit undefined behaviour. This is a property of the generated C we can state, test and enforce, not a hope.

The pitch is not "a nicer C". It is **"correct C, without writing C"**: the C is an artefact you can read, ship and audit, but never have to author.

## 2. Responses to the design thoughts

Each point is stated, then judged: what holds, where the risks are and what we recommend. Details live in `docs/design/`.

### 2.1 Scribe as human/AI interface that guarantees safe C
**Agree, and this is the right organising principle.** Two consequences:

- The guarantee must be *enumerable*. We keep a catalogue of C's undefined behaviours and, for each, the mechanism that rules it out (compile-time rejection, a checked runtime operation, or a construct that cannot be expressed). See [`ub-catalogue.md`](design/ub-catalogue.md). Every new feature must update that table before it ships.
- Rejecting is not enough; **the runtime behaviour on violation must also be defined**. Policy: a violated check (overflow, division by zero, and later array bounds) *traps*: it prints a located message and stops the program (`abort()`, so a nonzero exit status). No silent wraparound, no exceptions in v1. This is how integer overflow, integer division by zero and out-of-range float-to-integer casts behave today.
- Defence in depth: every program the test suite generates is built with `-std=c11 -pedantic-errors -Wall -Wextra`. The runtime-error tests always build with UBSan, so a check that fires too late shows up as a sanitizer report, and `SCRIBE_SANITIZE=1` builds every run with UBSan. AddressSanitizer joins once there is heap memory to check. The guarantee is only as good as the emitter and the hand-written runtime, so both are tested adversarially.
- AI-friendliness is a design input: one obvious way to do each thing, locally checkable rules, diagnostics precise enough to feed back into a model.
- `goto` is deprecated (warning W0001) now that `break` and `continue`, with named loops for outer loops, cover its uses; it will be removed in a future version. Every structured exit (`break`, `continue`, later `return`) is lowered so cleanups run on every exit edge.

### 2.2 Explicit typing first, a little inference later
**Agree, and implemented for scalars.** Inference is *local and one-directional*: a variable's type comes from its first assignment (a literal, a cast, later a constructor call or a function's return type) and never from later uses. No unification, no inference across statements. `x = 3` is an `i64`, `x = 3.0` an `f64`, `x = 2.5f` an `f32`; later, `a = Account(...)` will be an `Account`. Everything else is declared: `i64: x, y = 5`.

**Compatibility (decided).** Before version 0.3.0, `7` was a float; now it is an i64. Rather than an edition marker with a legacy float-only mode, the language made the breaking change before 1.0 and the examples were migrated. Numeric rules (implemented): no implicit conversion that could lose a value; implicit widening only where every value converts exactly (`f32` to `f64`); everything else through a cast written like a call, `f64(n)` or `i64(x)`; checked arithmetic by default. Wrapping arithmetic will only be available through visible operators (`+%`, planned). The full rules are in [`type-system.md`](design/type-system.md).

### 2.3 Typed functions with unions and overloading
**Agree with caution: this is the riskiest combination.** Unions plus overloading plus implicit widening produces ambiguity quickly. Proposal:

- Overloading resolves **statically** on exact argument types; then on lossless widening; ambiguity is a compile error (see `examples/future/errors/ambiguous_overload.scribe` and [functions.md](design/functions.md#7-overloading-multiplexing)). It is planned with functions in stage M3.
- Unions are **tagged** sum types. The only way to look inside is `match`, and `match` must be exhaustive.
- A union argument to an overloaded call is accepted only if *every* member resolves; the compiler then emits the dispatch switch. Otherwise it is an error. This gives unions and overloading one clear interaction instead of a pile of special cases.
- Return types are never used to pick an overload.
- Every overload lowers to a distinct, deterministically named C function, so the C stays boring.

### 2.4 Templating C programs for array libraries and the like
**Agree for the runtime library; do not expose it as the user's generics.** Two layers:

1. **Runtime templates** (hand-written, audited C with type holes: arrays, strings, maps, option/result, overflow-checked arithmetic) instantiated per type. This is the *trusted base*: if it has UB, every program does. It is small, tested under sanitisers and property-tested.
2. **User generics** (`fn f[T: Numeric]`, after structs and classes) are monomorphised in the Scribe IR *before* emission, so the C emitter never sees a type variable.

Text-level C templating (macros or string substitution) is cheap to start with but has no hygiene. We use a structured template format (placeholders for type, name and size only, checked at build time) instead of freeform macros. See [`lowering.md`](design/lowering.md).

### 2.5 Generated names, towards lowered monomorphised code
**Agree, and started.** Variables become `v_x`, labels `l_x`, temporaries `t_1` and runtime helpers `scribe_*`, so no Scribe name can clash with a C keyword or libc symbol. Scribe has no shadowing, so a name never needs a suffix. Extend to a scheme that is deterministic, readable and collision-free: `module__fn__sig` for functions, `Type__method`, `Array__i64__push`. Emit `#line` directives so debuggers and C diagnostics point back to Scribe source. Hash suffixes only as a last resort; readable output is part of the product.

### 2.6 No visible pointers; RAII with escape analysis; maybe ref counting later
**Agree on the goal. The key design decision is what replaces lifetimes.** Rust solves this with lifetime annotations; Scribe should not. Recommendation, based on mutable value semantics (Hylo, Swift-style `inout`):

- Aggregates (`struct`, `Array`, `str`) have **value semantics**: assignment is a (possibly lazy) copy or a move; no two live names alias the same mutable data.
- Function parameters are **borrowed by default** (read-only; `mut` for exclusive write access; `take` to move ownership in). Borrows are **second-class**: they may be passed down, but not stored in a field, captured, or returned. That single rule removes dangling references with no lifetime syntax.
- Exclusive access is checked: you cannot mutate a collection while an iterator borrows it. This kills iterator invalidation.
- Heap placement is **inferred**: values that don't escape live on the stack; escaping values get a unique owner and a compiler-inserted free on every exit path (including early `return`, `goto` and traps-that-clean-up).
- `class` means a *shared* reference type. Introduce it only with **deterministic reference counting**, which handles shared ownership without a GC. Cycles are the known hole: forbid by construction (weak references, or an acyclicity check) before shipping classes. Until then, stage M7 classes can be unique-owner only.

Open: stack depth. Unbounded recursion overflows the C stack, which is not defined behaviour we can check cheaply. See open questions.

### 2.7 Booleans and logical operators
**Implemented.** The choices follow the same principle as the numeric rules: nothing implicit that could surprise.

- `bool` lowers to `uint8_t`, not `_Bool`, so its C spelling and size are the same everywhere and a future `Array[bool]` is one byte per element. **Storage invariant:** every stored bool is exactly 0 or 1. It holds by construction: a bool starts at 0 and can only be given `true`/`false`, a comparison, `not`, `and`, `or`, `bool(n)` or another bool, and the C for each of those yields 0 or 1.
- **Truth tests** (conditions, operands of `not`/`and`/`or`) accept a bool or an integer. A float is a compile error, because "true unless 0.0" makes NaN true and `-0.0` false; programs write `x != 0.0`.
- `and` and `or` **short-circuit and return a bool**, lowered to C `&&` and `||`. Returning an operand, as Python does, would make the result's type depend on its operands. Short-circuiting is observable even though expressions have no side effects, because a runtime check is an effect: `n == 0 or 10 // n > 1` never divides by zero.
- **No implicit conversion** between bool and numbers in either direction, and no arithmetic or ordering on bools; `bool(n)` and `i64(flag)` are the explicit forms.
- **Comparison chains** (`a < b <= c`) mean what they do in Python, with the middle operand evaluated once. They must point one way, and `!=` cannot be chained, because `a != b != c` does not say all three differ.
- Precedence is Python's: `or` < `and` < `not` < comparisons.

### 2.8 Division
**Implemented.** Python 3's split, kept strict. `/` is float division: integer constants become floats (`7 / 2` is 3.5), and an integer variable is a compile error rather than a silent conversion that would round above 2^53. `//` and `%` divide integers and round toward negative infinity, as Python's do, so `%` has the sign of the divisor. Which division runs is decided by the operator, never by operand types the reader cannot see: in C, and in Scribe before this change, `f64: a = 7 / 2` quietly stored 3.0. `//` and `%` on floats come next: the naive `floor(a / b)` is not Python's answer, and they need `-lm`.

### 2.9 Powers, and only the libraries a program uses
**Implemented.** `**` has Python's precedence. On integers it is exact and checked (exponentiation by squaring through the checked multiply), never `pow`, because a double is exact only up to 2^53. On floats it is `pow`/`powf`, whose edge cases IEEE 754 defines; they differ from Python, which raises an error or returns a complex number. This is the first feature that needs a C library, so the compiler now tracks what each program uses: headers, `<stdio.h>` included, are added only when needed, and the libraries to link (`-lm`) are reported to the build files and written at the top of the C file. The same mechanism will carry the header and library of every `extern` binding.

## 3. Pipeline

```
source -> parse -> AST -> semantic analysis (scopes, types, ownership)
       -> typed IR -> monomorphise -> lower (checks, cleanups, names)
       -> C AST -> C text (+ #line)  -> cc
```

Today the pipeline is `parse -> AST -> semantics (scopes and types) -> C text`. Checked arithmetic did not need more: the emitter picks a small checked C helper from each expression's type. A **typed IR** between semantics and emission becomes necessary with functions and ownership, where lowering decisions (cleanups on every exit edge, moves, monomorphisation) must be made once, in one place, instead of inside string-building code.

## 4. Roadmap

| Stage | Adds | Safety work |
|---|---|---|
| M1 (done) | float-only, blocks, `goto`, strings in `print` | float literals, `puts`, name prefixes |
| M2 (in progress) | done: `i64`, `f64`, `f32`, `bool`, Python-style literals, declarations, chained and multiple assignment, casts, `/` `//` `%` `**`, `and`/`or`/`not`, conditions as expressions, comparison chains, `break`/`continue` with named loops (`goto` deprecated), headers and libraries only when used. Next: sized integers, float `//` and `%`; see [status and next steps](design/type-system.md#status-and-next-steps) | done: checked arithmetic, trap runtime, UBSan tests. Next: range analysis to remove provably safe checks |
| M3 | typed IR, runtime errors that propagate with tracebacks, functions, `return`, recursion, overloading, `use math`; see [functions.md](design/functions.md#10-roadmap) | strict evaluation order, exit analysis, recursion limit, ambiguity errors |
| M4 | arrays, strings, `for`, runtime templates | bounds checks, allocation-failure policy |
| M5 | `struct`, value semantics, borrow rules | exclusive access, move checking |
| M6 | unions, `match` | exhaustiveness |
| M7 | `class`, RAII, escape analysis | ownership of heap objects |
| M8 | generics, iterators | constraints checked at the definition, invalidation rules |
| M9 | reference counting | cycle policy |

Stages are plans, not versions: released versions and what each one changed are in [`CHANGELOG.md`](../CHANGELOG.md), and stage M2 so far spans versions 0.3.0 to 0.6.0.

**Deployment targets (off the stages).** Programs also build as WebAssembly, for Node or for a browser terminal (xterm.js with xterm-pty), from the same C: a proof that the C-first design deploys anywhere a C compiler reaches. A later step, once `use` and `extern` exist, is a `dom` module with JavaScript bindings, for programs with a web UI rather than a terminal ([lowering.md](design/lowering.md#targets)).

Order rationale: types before functions (signatures need them), arrays before structs (forces the runtime-template and heap machinery early, on the simplest type), functions with their error model before any heap type (cleanups need the error exits), ownership and classes before generics (generics over owned types are the hard case).

## 5. Open questions

1. **Trap vs. exceptions vs. `Result`.** Proposed in [runtime-errors.md](design/runtime-errors.md): every runtime error, checks included, returns through the callers kernel style, collecting a traceback, and `main` reports it in text or JSON. `raise`/`try`/`except`/`finally` build on that later. A bare `except` catches only raised errors; the errors of checks are caught only by name (`except OverflowError`).
2. **Stack overflow.** Proposed: a depth counter in functions that are part of a call-graph cycle, failing with R0005 past a limit of 1,000 ([runtime-errors.md](design/runtime-errors.md#6-recursion-limit)).
3. **Integer width.** Decided: sized types (`i8` ... `u64`), with i64 as the default for integer literals. i64 is implemented; the rest are next.
4. **Floats.** Decided: `f32` and `f64`, with f64 the default for float literals (`2.5f` is f32).
5. **C interop.** An `extern` mechanism is where pointers sneak back in. Proposal: a vetted, audited binding layer, not user-written.
6. **Concurrency.** Out of scope until the ownership model is settled; data races are UB we simply do not offer yet.
7. **Strings.** UTF-8 bytes with validated construction; indexing by byte or by code point?
8. **`goto`.** Decided: deprecated, with warning W0001, now that `break` and `continue` exist (`while cond as name` names a loop that an inner `break name` or `continue name` can reach). It will be removed in a later breaking version. Multi-level exits use names rather than counts (`break 2`), so moving code in or out of a loop can never silently change the target.

## 6. Non-goals

Not a C replacement for systems code that needs raw pointers; not a macro system; no unsafe escape hatch in v1 (if one is ever added it is a compiler-audited module, not a keyword).

## 7. Supporting documents

- [`design/ub-catalogue.md`](design/ub-catalogue.md) - every C UB we must rule out, and how.
- [`design/type-system.md`](design/type-system.md) - types, conversions, inference, booleans, overloading, unions.
- [`design/memory-model.md`](design/memory-model.md) - value semantics, borrows, RAII, escape analysis, RC.
- [`design/lowering.md`](design/lowering.md) - naming, templates, monomorphisation, emitted C shape.
- [`design/functions.md`](design/functions.md) - functions, argument passing, exit analysis, overloading (draft).
- [`design/runtime-errors.md`](design/runtime-errors.md) - error kinds, propagation, tracebacks (draft).
- [`../examples/README.md`](../examples/README.md) - runnable examples and proposed syntax.
