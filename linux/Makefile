.PHONY: run test deb appimage clean

run:
	python3 -m claude_usage

test:
	python3 -m pytest tests/ -v

deb:
	bash packaging/build-deb.sh

appimage:
	bash packaging/build-appimage.sh

clean:
	rm -rf build/ dist/ *.deb *.AppImage
