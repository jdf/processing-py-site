#!/usr/bin/python
from __future__ import with_statement, print_function
from xml.etree import ElementTree as ET
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
    source_xml = ET.parse(src_file)
    result_html = copy.deepcopy(template_reference_page)




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
    print("source file name, path:",source_file_name,source_file_path)
    dest_file_path = target_dir + source_file_name[:-4] + '.html'
    try:
        #htmlgen_old.translate_file(source_file_path, dest_file_path)

        print('Translated %s' % source_file_path)
    except Exception, e:
        print('Failed to translate %s:' % source_file_path)
        print(e)
print('Copying static resources...')
distutils.dir_util.copy_tree('./content', target_dir)
print('Done.')

