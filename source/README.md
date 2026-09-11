# Source icon sheet

This directory is for Splunk’s documentation icon sheet. **Do not commit the PNG.**

From the repo root:

```bash
uv run python run_pipeline.py download
```

That fetches the Transparent PNG from [Draw a diagram of your deployment](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.4/inherited-deployment-tasks/draw-a-diagram-of-your-deployment) and saves it here as:

```text
source/Splunk_Documentation_Icons_August2018.png
```

The workbench **Download icon sheet** button does the same. If Splunk moves the file, the command fails and prints that docs URL so you can save the PNG here by hand.

The sheet is Splunk artwork. Splunk makes it available so you can diagram **your own Splunk deployment**. It is not an open license to republish the icons.
