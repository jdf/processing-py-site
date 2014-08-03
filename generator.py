#!/usr/bin/python
from __future__ import with_statement, print_function
from lxml import etree as ET # We need to use lxml because it can handle CDATA tags
from argparse import ArgumentParser

import os
import re
import shutil
import distutils.core
import sys
import copy
import datetime

try:
    import jinja2
except:
    print("I can't import jinja2 for some reason.")
    print("Please run pip install -r requirements.txt before using generator.py.")

def convert_hypertext(element, toplevel=True):
    """
    Recursively creates a string with properly-resolved links and whatnot from an element in an element-tree.
    Used directly from jinja.
    """
    if element.tag == 'br':
        return '<br />'
    text = ''
    if element.tag == 'c':
        tag = 'kbd'
    else:
        tag = element.tag
    if not toplevel:
        text += '<{}>'.format(tag)
    if element.text:
        text += element.text
    for child in element:
        text += convert_hypertext(child, toplevel=False)
        if child.tail:
            text += child.tail
    if not toplevel:
        text += '</{}>'.format(tag)
    return text 

def format_code(code):
    escape_chars = {
            '\n': '<br />',
            ' ' : '&nbsp;',
            '\t': '&nbsp;&nbsp;&nbsp;&nbsp'
            }
    return "".join((escape_chars.get(c, c) for c in code))

class ReferenceItem:
    '''Represents a single page of reference information.'''
    def __init__(self, source_xml):
        xml = ET.parse(source_xml)
        if xml.find('name') is not None:
            self.name = xml.find('name').text
        if xml.find('type') is not None:
            self.type = xml.find('type').text
        if xml.find('example') is not None:
            self.examples = []
            for example in xml.iterfind('example'):
                self.examples.append({'code': format_code(example.find('code').text)}) 
        if xml.find('description') is not None:
            self.description = convert_hypertext(xml.find('description'))
        if xml.find('syntax') is not None:
            self.syntax = convert_hypertext(xml.find('syntax'))
        if xml.find('parameter') is not None:
            self.parameters = []
            for parameter in xml.iterfind('parameter'):
                label = parameter.find('label').text
                description = convert_hypertext(parameter.find('description'))
                self.parameters.append({'label':label, 'description':description})
        if xml.find('related') is not None:
            self.related = xml.find('related').text

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

    today = datetime.datetime.now().ctime()

    for source_file_name in to_update:
        source_file_path = src_dir + source_file_name
        source_info = ReferenceItem(source_file_path)
        target_file_path = target_dir + source_file_name[:-4] + '.html'
        with open(target_file_path, 'w') as target_file:
            rendered = reference_template.render(item=source_info, today=today)
            target_file.write(rendered.encode('utf-8'))
            print("Rendered {} to {}.".format(source_file_path, target_file_path))

    print('Copying static resources...')
    distutils.dir_util.copy_tree('./content', target_dir)
    print('Done.')

def test(target_dir='./generated'):
    print_header("Testing")
    import random, SimpleHTTPServer, SocketServer, webbrowser
    socket = random.randrange(8000, 8999)
    address = "http://localhost:{}".format(socket)
    print("Serving on {}".format(address)) 
    os.chdir(target_dir)
    httpd = SocketServer.TCPServer(("localhost", socket), SimpleHTTPServer.SimpleHTTPRequestHandler)
    webbrowser.open(address)
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
