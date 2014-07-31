#!/usr/bin/python
from __future__ import with_statement, print_function
from xml.etree import cElementTree as ET
from optparse import OptionParser

import os
import re
import shutil
import distutils.core
import sys
import copy

import htmlgen_old


def get_files_to_update(src_dir, target_dir):

    def should_be_updated(f):
        src_f = src_dir + f
        if not f.endswith('.xml'):
            return False
        target_f = '%s/%s.html' % (target_dir, f[:-4])
        if not os.path.exists(target_f):
            return True
        return os.path.getmtime(src_f) > os.path.getmtime(target_f)
    
    files = filter(should_be_updated, os.listdir(src_dir))

    return files

def translate_reference_file(src_file, target_file):
    print("Translating", src_file, "to", target_file)
    source_xml = ET.parse(src_file)
    result_html = copy.deepcopy(template_reference_page)
    print("\033[95m")
    print("=======================================")
    name = source_xml.find("name")
    if name is not None and name.text is not None:
        print(name.text)
    category = source_xml.find("category")
    subcategory = source_xml.find("subcategory")
    if category is not None and subcategory is not None and category.text is not None and subcategory.text is not None:
        print("    (%s/%s)" % (category.text, subcategory.text))
        print("=======================================")
        print()
    description = source_xml.find("description")
    if description is not None and description.text is not None:
        print("Description:")
        print("   " + description.text.replace("\n", "\n   "))
    for example in source_xml.iterfind("example"):
        ex_code = example.find("code").text
        print("Example: ")
        print("   " + ex_code.replace("\n", "\n   "))
    syntax = source_xml.find("syntax")
    if syntax is not None and syntax.text is not None:
        print("Syntax:")
        print("   " + syntax.text.replace("\n", "\n   "))
    for parameter in source_xml.iterfind("parameter"):
        print("   %s: %s" % (parameter.find("label").text, parameter.find("description").text))
    returns = source_xml.find("returns")
    if returns is not None and returns.text is not None:
        print()
        print("Returns:", returns.text)
    availability = source_xml.find("availability")
    if availability is not None and availability.text is not None:
        print()
        print("Availability:", availability.text)
    typ = source_xml.find("type")
    if typ is not None and typ.text is not None:
        print()
        print("Type:", typ.text)
    partof = source_xml.find("partof")
    if partof is not None and partof.text is not None:
        print()
        print("Part of:", partof.text)
    related = source_xml.find("related")
    if related is not None and related.text is not None:
        print()
        print("Related:")
        print(related.text.replace("\n", "\n   "))
    print("=======================================")
    print("\033[0m")

src_dir = './Reference/api_en/'
target_dir = './generated/'
template_dir = './template/'
template_reference_page = ET.parse(template_dir + 'reference_item_template.html')

if not os.path.exists(target_dir):
    os.makedirs(target_dir)
if not os.path.exists(src_dir):
    print('Go to the root of the repo for now, please')
    sys.exit(1)
to_update = get_files_to_update(src_dir, target_dir)
print('%s stale files to be translated' % len(to_update))
for source_file_name in to_update:
    source_file_path = src_dir + source_file_name
    dest_file_path = target_dir + source_file_name[:-4] + '.html'
    #try:
        #htmlgen_old.translate_file(source_file_path, dest_file_path)
    translate_reference_file(source_file_path, dest_file_path)
    #except Exception, e:
    #    print('Failed to translate %s:' % source_file_path)
    #    print(e)
print('Copying static resources...')
distutils.dir_util.copy_tree('./content', target_dir)
print('Done.')

