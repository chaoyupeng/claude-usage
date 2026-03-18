.PHONY: run test deb clean

run:
	python3 -m claude_usage

test:
	python3 -m pytest tests/ -v

deb:
	bash packaging/build-deb.sh

clean:
	rm -rf build/ dist/ *.deb
