# Processing Py Site


The script `Reference/api_en/htmlgenerator.py` generates .html Reference pages from the .xml files in the same directory.

Run it using this line, which assumes you are in Reference/api_en:

<pre>for file in *.xml; do python htmlgenerator.py $file htmlconversions/${file%.*}_.html; done </pre>


