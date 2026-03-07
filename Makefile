.PHONY: test clean

test:
	python3 -m pytest tests/ -v

test-unit:
	python3 -m unittest discover tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
