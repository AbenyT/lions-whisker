PY ?= python

.PHONY: film radio validate narration keyframes shots music assemble mock clean
film:        ## whole pipeline, both aspect ratios
	$(PY) pipeline/run_all.py
radio:       ## narration + score on black, for the first audience test
	$(PY) pipeline/run_all.py --radio
validate:
	$(PY) pipeline/validate.py
narration:
	$(PY) pipeline/narration.py
keyframes:
	$(PY) pipeline/keyframes.py
shots:
	$(PY) pipeline/shots.py
music:
	$(PY) pipeline/music.py
assemble:
	$(PY) pipeline/assemble.py
mock:        ## offline dry run with placeholder media, no keys needed
	PIPELINE_MOCK=1 $(PY) pipeline/run_all.py
clean:       ## delete generated media (keeps runs.jsonl)
	rm -rf outputs/narration outputs/refs outputs/keyframes outputs/shots outputs/subs outputs/*.mp4 outputs/timeline.json
