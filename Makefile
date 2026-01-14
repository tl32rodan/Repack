.PHONY: test demo clean

test:
	python3 -m unittest discover tests

demo:
	bin/repack demo/demo.py

clean:
	rm -rf demo/repack_status.csv demo/output
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete
