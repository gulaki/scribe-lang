// Runs a Scribe program, built by Emscripten for the web shell, in an xterm.js
// terminal. xterm-pty gives it a real terminal (echo, line editing, Ctrl-C,
// Ctrl-D for end of input), and Emscripten's Asyncify lets `input` wait for a
// line without blocking the page. Written by `scribe --target wasm`.

const THEME_KEY = "scribe-term-theme"; // shared by every Scribe app on this origin
const THEMES = {
  light: {
    background: "#ffffff", foreground: "#1e1e1e", cursor: "#1e1e1e", cursorAccent: "#ffffff",
    selectionBackground: "#add6ff", red: "#cd3131", brightRed: "#e51400",
  },
  dark: {
    background: "#1e1e1e", foreground: "#e6e6e6", cursor: "#e6e6e6", cursorAccent: "#1e1e1e",
    selectionBackground: "#264f78", red: "#f14c4c", brightRed: "#ff6b6b",
  },
};
const systemDark = matchMedia("(prefers-color-scheme: dark)");

// The saved choice: "system", "light" or "dark". Storage can be unavailable
// (a private window, blocked site data); then the choice lasts for the page.
function savedChoice() {
  try {
    return localStorage.getItem(THEME_KEY) || "system";
  } catch {
    return "system";
  }
}

function saveChoice(choice) {
  try {
    if (choice === "system") {
      localStorage.removeItem(THEME_KEY);
    } else {
      localStorage.setItem(THEME_KEY, choice);
    }
  } catch {
    // Not saved; the page still uses the choice.
  }
}

function themeFor(choice) {
  return choice === "system" ? (systemDark.matches ? "dark" : "light") : choice;
}

if (location.protocol === "file:") {
  document.getElementById("file-warning").hidden = false;
}

const term = new Terminal({
  cursorBlink: true,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
  fontSize: 14,
  theme: THEMES[themeFor(savedChoice())],
});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById("terminal"));
fit.fit();
addEventListener("resize", () => fit.fit());

const { master, slave } = openpty();
term.loadAddon(master);

const select = document.getElementById("theme");
function applyTheme(choice) {
  const theme = themeFor(choice);
  document.documentElement.dataset.theme = theme;
  term.options.theme = THEMES[theme];
}
select.value = savedChoice();
applyTheme(select.value);
select.addEventListener("change", () => {
  saveChoice(select.value);
  applyTheme(select.value);
  term.focus();
});
systemDark.addEventListener("change", () => {
  if (select.value === "system") {
    applyTheme("system");
  }
});
document.getElementById("rerun").addEventListener("click", () => location.reload());

// One closing line: dim for a normal exit, red for anything else. It goes
// through the pty, so it comes after the program's own output, which may
// still be queued there.
let finished = false;
function finish(message, failed) {
  if (finished) {
    return;
  }
  finished = true;
  slave.write(`\n\x1b[${failed ? "31" : "2"}m[${message}]\x1b[0m\n`);
}

term.focus();
const program = document.body.dataset.program;
let start = null;
try {
  ({ default: start } = await import(`./${encodeURIComponent(program)}.mjs`));
} catch {
  finish(`${program}.mjs is missing: build it first (make, or ninja, in this folder)`, true);
}
if (start !== null) {
  try {
    await start({
      pty: slave,
      onExit: (status) => finish(`program exited with status ${status}`, status !== 0),
      // A Scribe runtime error has already printed its message; abort() ends it.
      onAbort: () => finish("program stopped by a runtime error", true),
    });
  } catch {
    finish("program stopped by a runtime error", true);
  }
}
