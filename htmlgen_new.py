#!/usr/bin/python
from __future__ import with_statement, print_function
from xml.etree import ElementTree as ET
from optparse import OptionParser

import os
import re
import shutil
import sys

def get_files_to_update(src_dir, target_dir):

    def should_be_updated(f):
        if not f.endswith('.xml'):
            return False
        target_f = '%s/%s_.html' % (target_dir, f[:-4])
        if not os.path.exists(target_f):
            return True
        return os.path.getmtime(f) > os.path.getmtime(target_f)
    
    files = filter(should_be_updated, os.listdir(src_dir))

    return files


print(get_files_to_update('.', './htmlconversions'))

