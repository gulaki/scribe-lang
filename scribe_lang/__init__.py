from .compiler import CompilationResult, Compiler
from .parser import Parser
from .version import version

__version__ = version()

__all__ = ["CompilationResult", "Compiler", "Parser", "__version__"]
