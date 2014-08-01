#!/usr/bin/python
from __future__ import with_statement, print_function
from xml.etree import cElementTree as ET
from argparse import ArgumentParser

import os
import re
import shutil
import distutils.core
import sys
import copy

try:
    import jinja2
except:
    print("I can't import jinja2 for some reason.")
    print("Please run pip install -r requirements.txt before using generator.py.")

class ReferenceInfo:
    def __init__(self, source_xml):
        pass#xml = et.element_tree

def print_header(text):
    print('=== \033[95m{}\033[0m ==='.format(text))

def print_error(text):
    print('\033[91mError: {}\033[0m'.format(text))

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

def build(src_dir='./Reference/api_en/', target_dir='./generated/', template_dir='./template/', all=False, one=False):
    print_header("Building content")
    if one:
        shutil.rmtree(target_dir)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    if not os.path.exists(src_dir):
        print('Go to the root of the repo for now, please')
        sys.exit(1)
    if all:
        to_update = filter(lambda x: x.endswith('.xml'), os.listdir(src_dir))
    else:
        to_update = get_files_to_update(src_dir, target_dir)
    if one:
        to_update = to_update[0:1]
    
    print('%s stale files to be translated' % len(to_update))

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
    reference_template = env.get_template("reference_item_template.jinja")

    for source_file_name in to_update:
        source_file_path = src_dir + source_file_name
        source_info = ReferenceInfo(source_file_path)
        target_file_path = target_dir + source_file_name[:-4] + '.html'
        with open(target_file_path, 'w') as target_file:
            target_file.write(reference_template.render(source_info))
        print("Rendered {} to {}.".format(source_file_path, target_file_path))

    print('Copying static resources...')
    distutils.dir_util.copy_tree('./content', target_dir)
    print('Done.')

def test(target_dir='./generated'):
    print_header("Testing")
    print("Serving on http://localhost:8000")
    import SimpleHTTPServer, SocketServer, webbrowser
    os.chdir(target_dir)
    httpd = SocketServer.TCPServer(("localhost", 8000), SimpleHTTPServer.SimpleHTTPRequestHandler)
    webbrowser.open("http://localhost:8000")
    httpd.serve_forever()

if __name__ == '__main__':
    class DefaultHelpParser(ArgumentParser):
        def error(self, message):
            print_error(message)
            print()
            self.print_help()
            sys.exit(1)

    parser = DefaultHelpParser(description='Management script for py.processing.org')
    subparsers = parser.add_subparsers(dest='command')
    build_parser = subparsers.add_parser('build', description='Build web pages from reference source')
    build_parser.add_argument('--all', action='store_true', help='Rebuild fresh pages as well as stale ones')
    build_parser.add_argument('--one', action='store_true', help='Build only one file (for testing purposes)')
    test_parser = subparsers.add_parser('test', description='Test locally')
    args = parser.parse_args()
    if args.command == 'build':
        build(all=args.all, one=args.one)
    elif args.command == 'test':
        test()
