venv::
	rm -rf venv
	python -m venv venv
	./venv/bin/python -m pip install -U pip
	./venv/bin/pip install -r requirements.txt


config::
	./venv/bin/python scan4device.py

app::
	./venv/bin/python app.py