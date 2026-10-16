.PHONY: test demo clean

test:
	python -m pytest

demo:
	mkdir -p build
	python -m scribe_lang.cli examples/fibonacci.scribe -o build/fibonacci.c --build make --build-output build/Makefile

clean:
	rm -rf build/*.c build/Makefile build/*.ninja build/fibonacci
