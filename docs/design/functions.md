# Functions (draft specification)

Status: **draft 2, proposed.** The decisions made so far are in
[section 11](#11-decisions). Nothing here is implemented yet. Runtime
errors and tracebacks, which every function call depends on, are specified
in [runtime-errors.md](runtime-errors.md). The order of the work is in
[section 10](#10-roadmap).

## 1. Defining a function

```text
fn gcd(i64: a, i64: b) -> i64 {
    while b {
        a, b = b, a % b
    }
    return a
}

fn greet() {
    print "hello"
}

print gcd(48, 18)
greet()
```

- `fn name(parameters) -> type { body }`. Without `-> type`, the function
  returns no value and can only be called as a statement.
- Each parameter is written `type: name`, like a declaration, and has its own
  type: `(i64: a, i64: b)`. There is no shared form like `(i64: a, b)`,
  because it would read like two parameters with one being untyped.
- Functions are declared only at the top level of a file: no nested
  functions and no closures in v1.
- **Order does not matter.** A function may be called above its definition,
  and functions may call each other recursively. The compiler reads all
  definitions first and emits a C prototype for each.
- The program's top-level statements stay the program: they become `main`.
  Function definitions may appear among them and do not run.
- New reserved words: `fn`, `return` and `global`, and later `mut`, `use`,
  `extern`, `raise`, `try`, `except` and `finally`.

## 2. Names and scope

- A function body is a scope. Its parameters and the variables it creates
  are local to it.
- **A function does not see program-level variables** unless it names them
  with `global`. Without it, a function sees only its parameters, its own
  variables and other functions, so it can be tested on its own and every data
  flow shows at the call. `global` makes the exception explicit (section 2.1).
- Functions and variables share one namespace per file, as in Python. A
  variable may not have the name of a function, or the reverse (E07xx), in
  keeping with Scribe's no-shadowing rule.
- Labels are local to a function, and `break`/`continue` can't leave a
  function. `goto` is deprecated (W0001) and will be removed, ideally before
  functions arrive.

### 2.1 `global`

```text
count = 0

fn tick() {
    global count
    count = count + 1
}

tick()
tick()
print count          # 2
```

- `global a, b` names program-level variables that the function reads or
  assigns. It must come before the function's first use of those names; by
  convention it is the first line of the body.
- Each name must be a program-level variable, one that a top-level statement
  assigns or declares somewhere in the file (E07xx unknown-global). Its type
  is that variable's type. A function may run before that statement does;
  the variable is then 0, like every variable before its first assignment.
- Using a program-level variable without `global` is E0201 (undeclared
  variable), with a note: "'count' is a program-level variable; write
  `global count` to use it here".
- A function can't declare a local with the name of a program-level
  variable it can see through `global` (no shadowing). One it does *not* name
  in `global` is invisible, so a local may reuse the name.
- Functions never need `global`: every function is visible everywhere in the
  file.
- C: program-level variables are already file-scope globals (`v_count`), so a
  `global` name is used directly. A function that names any `global` can't be
  treated as pure by later optimisations.
- Every variable starts at 0, as at the top level.

## 3. Calls and arguments

- `name(arguments)` is an expression when the function returns a value, and
  a statement either way. A returned value may be ignored.
- **Arguments are evaluated left to right, each completely, before the
  call.** With `f(a) + g(b)`, `f` is called before `g`.
- The number of arguments must match (E07xx). v1 has no default values, no
  variable argument lists and no keyword arguments. Defaults complicate
  overloading; keyword arguments are worth adding later, because they make
  calls easier to read.
- Each argument converts to its parameter type by the assignment rule:
  lossless, or an error. `f(3)` for an `f64` parameter is fine, but an `i64`
  variable for an `f64` parameter needs `f64(n)`. With overloads, that rule
  is applied through overload resolution (section 7).
- A call runs only when it is reached: in `n == 0 or f(n)`, `f` is not called
  when `n == 0`. The same holds for a call in the middle operand of a
  comparison chain.

## 4. Passing arguments

| Mode | Written | Meaning | C |
|---|---|---|---|
| value (default) | `fn f(i64: a)` | `a` is a local variable that starts as a copy of the argument. The function may assign to it; the caller never sees the change. | `int64_t v_a` |
| `mut` (later) | `fn f(mut i64: a)`, called `f(mut x)` | The function works on the caller's variable: assignments to `a` change `x`. The argument must be a variable, and `mut` is written at the call too, so the change is visible where it happens. | `int64_t *p_a` |
| `take` (with heap types) | `fn f(take Array[i64]: a)` | Ownership moves into the function; the caller can't use the value afterwards. | by value |

- **Exclusivity.** A variable passed as `mut` can't be passed again in the
  same call, neither as `mut` nor as a value (E07xx). So `swap(mut a, mut a)`
  is rejected, and a `mut` parameter never aliases anything, which is what
  memory-model.md requires.
- For scalars, the default is a plain C copy. For arrays and strings later,
  the default is *implemented* as a borrow (memory-model.md §2): passed by
  pointer, and copied only if the function assigns to it. The visible rule
  stays "a parameter is a copy".
- Only one value is returned. Returning several values (`q, r = divmod(a, b)`)
  waits for tuples, and will fit the existing multiple assignment.

## 5. Returning and exit analysis

The compiler builds each function's control-flow graph and checks every way
out of it.

| Rule | Error |
|---|---|
| A function with `-> T` must `return` a value on every path. `while true { }` without a way out counts as never reaching the end. | E07xx missing-return |
| `return` without a value in a function with `-> T`, or `return value` in a function without one | E07xx |
| `return` outside a function | E07xx |
| A statement after `return`, `break` or `continue` | warning W0002 unreachable-code |
| The returned value converts to `T` by the assignment rule | E0501 |

Every exit edge (`return`, the end of the body, a runtime error, and later
`break`/`continue` and `finally`) runs the cleanups of the scopes it leaves.
Today no scalar needs a cleanup, but the lowering already uses a single
error exit per function, so the cleanup ladder of memory-model.md §3 has
somewhere to go.

The top-level program has no `return`. It ends at its last statement with
status 0, or with status 1 after an uncaught runtime error
(runtime-errors.md §5). Ending early with `exit(n)` is planned.

## 6. Recursion

Recursion is allowed. A function that is part of a cycle in the call graph
counts its depth, and past the recursion limit the call fails with
`RecursionError` (R0005), which comes with a traceback. A C stack overflow,
which C does not define, therefore never happens. Non-recursive functions
pay nothing.

- The limit is 1,000 calls by default, Python's default, and
  `scribe --recursion-limit N` changes it. This is a resource bound, like
  stack size, so it doesn't break the rule that compiler flags never change
  what a program means. A program within the limit behaves the same with any
  limit.
- Tail calls are not optimised in v1. Guaranteed tail calls may come much
  later.

## 7. Overloading (multiplexing)

Several functions may share a name if their parameter types differ.
Overloading comes in stage M3, right after plain functions (roadmap F5): `use
math` (F6) needs it for `pow` on both `f32` and `f64`. Its prerequisites are
functions and the conversion rule, both already there. Sized integers (task
3) make it more useful but aren't required.
`math.pow` will be both `pow(f64: x, f64: y) -> f64` and
`pow(f32: x, f32: y) -> f32`.

**Resolution**, per call, at compile time:

1. The candidates are the functions with the name and the number of
   arguments.
2. If exactly one candidate matches every argument exactly, it is chosen.
3. Otherwise the candidates are the ones every argument converts to without
   loss. If exactly one needs no more conversions than any other, parameter by
   parameter, it is chosen. If several are incomparable, the call is
   ambiguous (E07xx), and the error lists them.
4. The return type and the surrounding context are never consulted.

**Constants.** An integer constant matches `i64` exactly, and `f64`/`f32` by
conversion if its value is exact there. A float constant matches `f64`
exactly, and `f32` by conversion. So `scale(2, 3)` picks `scale(i64, i64)`,
and `scale(2, 3.0)` picks `scale(f64, f64)`.

**Rules for the definitions:**
- Two overloads with the same parameter types are an error, even if their
  return types differ.
- `mut` is not part of the type: `f(i64)` and `f(mut i64)` can't both exist.
- A bool never converts, so `f(bool)` and `f(i64)` never compete.
- All overloads of a name come from one file or module; `use` never merges
  overload sets from different modules (see the `use` design, still to
  write).

Operators are already resolved this way (type-system.md, "Overloading").
User operator overloads will join the same sets once classes exist.

## 8. Evaluation order and lowering

Calls can fail, so they can't stay inside C expressions. The compiler
gains the **typed IR** promised in the whitepaper: each expression with a
call or a checked operation is lowered to **one operation per statement**,
into temporaries, with each fallible step checked at once. Operands and
arguments run strictly left to right. This also fixes UB-catalogue row 9's
gap for every expression.

```text
fn fact(i64: n) -> i64 {
    if n <= 1 {
        return 1
    }
    return n * fact(n - 1)
}
```

```c
static scribe_err f_fact__i64(int64_t v_n, int64_t *r_result);

static scribe_err f_fact__i64(int64_t v_n, int64_t *r_result) {
    int64_t t_1 = 0;
    int64_t t_2 = 0;
    int64_t t_3 = 0;
    if (scribe_enter(4) != 0) {          /* recursion limit; site 4 */
        return 1;
    }
    if (v_n <= INT64_C(1)) {
        *r_result = INT64_C(1);
        scribe_leave();
        return 0;
    }
    if (scribe_sub_i64(v_n, INT64_C(1), &t_1, 1) != 0) {
        goto fail;
    }
    if (f_fact__i64(t_1, &t_2) != 0) {
        scribe_trace(2);                  /* this call, for the traceback */
        goto fail;
    }
    if (scribe_mul_i64(v_n, t_2, &t_3, 3) != 0) {
        goto fail;
    }
    *r_result = t_3;
    scribe_leave();
    return 0;
fail:
    scribe_leave();
    return 1;
}
```

- **Names** follow lowering.md: `f_<name>__<parameter types>`, and later
  `f_<module>__<name>__<types>` for a module. Every function is `static`
  except `main`. Parameters are `v_<name>`, as for any variable, and the
  result pointer is `r_result`.
- **`and`, `or` and chains** whose right side contains a call or a check
  become `if` statements, so the right side still runs only when needed.
- Expressions with nothing that can fail (float arithmetic, comparisons of
  variables) may stay as one C expression; the code stays readable.
- The C keeps the shape rules of lowering.md: one statement per line, locals
  declared at the top of the block, and no macros.

## 9. Functions from C libraries

Bindings to C, the Cython-style `extern` blocks, are part of the standard
library design, to be written next. The plan: `use math` makes
`math.sqrt(x)` available. Its declarations are audited bindings, scalars
only and no pointers, which name the header and the library to link.
Calls to them go through the header and library tracking that `**` added.
A C function never fails in the Scribe sense, so a binding returns its
value directly. A binding that needs a check (`abs` of INT64_MIN) is
written in Scribe instead of being bound.

## 10. Roadmap

Each step is a task with failing tests first, as before.

| # | Step | Visible change |
|---|---|---|
| F1 | Typed IR: expressions with checked operations lowered to one operation per statement | none; strict left-to-right order (UB row 9) |
| F2 | Runtime errors propagate to `main`: status-returning helpers, the error record, R codes, text and JSON reports, exit status 1 | runtime errors get codes, and the exit status changes from abort to 1 |
| F3 | `fn`, parameters by value, `return`, calls, `global`, prototypes, exit analysis (missing return, W0002), the shared namespace rule | functions |
| F4 | Tracebacks across calls, recursion limit R0005 | tracebacks |
| F5 | Overloading | several functions with one name |
| F6 | `use math` and the first audited `extern` bindings | `math.sqrt`, `math.floor`, ... |
| F7 | `mut` parameters and exclusivity | in-out parameters |
| F8 | `raise`, `try`/`except`/`finally` | catching errors |

Tuples (several return values), keyword arguments, `exit(n)` and tail calls
come later. Generics come after structs and classes (whitepaper roadmap,
0.8). F1 and F2 change no syntax, so they can be finished and
released before the first `fn` parses.

## 11. Decisions

Decided (2026-10-23):

1. Parameters are written `type: name`, one type per parameter (section 1).
2. Functions see program-level variables only through `global`, which makes
   the non-locality explicit (section 2.1).
3. The recursion limit is 1,000 by default, with `--recursion-limit` to change
   it; tail calls come much later (section 6).
4. Overloading arrives in stage M3, after plain functions and before `use math`,
   which needs it (section 7).
5. Generics come after structs and classes.
6. Errors are returned, not aborted (runtime-errors.md §2).

Proposed, not yet confirmed:

- A parameter is an assignable local copy, and `mut` is written at the call
  too (section 4).
- No default values, no variable argument lists, and no keyword arguments in
  v1 (section 3).
- A returned value may be ignored (section 3).
