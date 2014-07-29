#!/usr/bin/python
# This program generates .html reference pages from corresponding .xml files.

# Run this line to generate html files in a directory called htmlconversions.
# for file in *.xml; do python htmlgenerator.py $file htmlconversions/${file%.*}_.html; done



from __future__ import with_statement
from xml.dom.minidom import parseString

from optparse import OptionParser
import os
import re
import shutil
import sys

firstexamplehtml = '''<tr class=""><th scope="row">Examples</th><td><div class="example"><img src="images/@picname" alt="example pic" /><pre class="margin">
@code
</pre></div>'''

exampleshtml = '''<div class="example"><img src="images/size_1.png" alt="example pic" /><pre class="margin">
@code
</pre></div>'''


firstparamhtml = '''<tr class="">   <th scope="row">Parameters</th><td><table cellpadding="0" cellspacing="0" border="0"><tr class="">
<th scope="row" class="code">@paramname</th>
<td>@paramdescription</td>
</tr>'''

paramshtml = '''<tr class="">
<th scope="row" class="code">@paramname</th>
<td>@paramdescription</td>
</tr>'''

template = None

with open ("template/reference_item_template.html", "r") as myfile:
    template = myfile.read()

# Replace tags that appear once at most.
def replaceSingleTags(dom):
    global template
    nameTag = dom.getElementsByTagName('name')
    name = nameTag[0].toxml().replace('<name>','').replace('</name>','')
    descriptionTag = dom.getElementsByTagName('description')
    description = descriptionTag[0].toxml().replace('<description><![CDATA[','').replace(']]></description>','')
    syntaxTag = dom.getElementsByTagName('syntax')
    if len(syntaxTag) != 0:
        syntax = syntaxTag[0].toxml().replace('<syntax>','').replace('</syntax>','')
        syntax = syntax.replace('<c>','<kbd>').replace('</c>','</kbd>')
        template = template.replace('@name',name).replace('@description',description).replace('@syntax',syntax)
    else:
        template = template.replace('@name',name).replace('@description',description)
      

# Replace tags with example code. 
def replaceExampleTags(dom):
    global template
    exampleTags = dom.getElementsByTagName('example')
    allExamples = ''
    first = True
    for exampleTag in exampleTags:
        imgTag = exampleTag.getElementsByTagName('image')
        imageName = imgTag[0].toxml().replace('<image>','').replace('</image>','')
        codeTag = exampleTag.getElementsByTagName('code')
        code = codeTag[0].toxml().replace('<code><![CDATA[','').replace(']]></code>','')
        if first:
            thisExample = firstexamplehtml.replace('@picname',imageName).replace('@code',code)
            first = False
        else:
            thisExample = exampleshtml.replace('@picname',imageName).replace('@code',code)
        allExamples += thisExample + '\n\n'
    template = template.replace('@examples', allExamples)

# Replace tags with parameter descriptions.        
# TODO combine replaceExampleTags and replaceParamTags
def replaceParamTags(dom):
    global template
    allParameters = ''
    paramTags = dom.getElementsByTagName('parameter')
    if len(paramTags) != 0:
        first = True
        for paramTag in paramTags:
            labelTag = paramTag.getElementsByTagName('label')
            label = labelTag[0].toxml().replace('<label>','').replace('</label>','')
            descriptionTag = paramTag.getElementsByTagName('description')
            description = descriptionTag[0].toxml().replace('<description>','').replace('</description>','')
            if first:
                thisParam = firstparamhtml.replace('@paramname',label).replace('@paramdescription',description)
                first = False
            else:
                thisParam = paramshtml.replace('@paramname',label).replace('@paramdescription',description)
            allParameters += thisParam 
        allParameters += '</table></td> </tr>'
        template = template.replace('@parameters', allParameters)        
     

def translate_file(s, d):
    with open(s, 'rb') as f:
        xml_file = f.read()
        dom = parseString(xml_file)
        # Get name and description and syntax from XML file and substitute it in HTML file.
        replaceSingleTags(dom)
        # Insert examples.
        replaceExampleTags(dom) 
        # Insert parameter descriptions.
        replaceParamTags(dom)
        with open(d, 'wb') as f:
            f.write(template)
