#!/usr/bin/env python
from __future__ import division, with_statement, print_function
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
    import lxml.html
    from lxml import etree # We need to use lxml because it can handle CDATA tags
except:
    print("I can't import my dependencies for some reason.")
    print("Please run pip install -r requirements.txt before using generator.py.")
    sys.exit(1)

def create_link(name):
    return name + '.html' # We might change this later

def make_convert_hypertext(names_dict):
    """
    Create a function to convert etree.Elements into properly-formatted HTML.
    The function is used directly from jinja.
    """
    def convert_hypertext(element, _toplevel=True):
        # Tags we don't need to recurse on
        if element.tag == 'br':
            return '<br />'
        if element.tag == 'ref':
            target = element.text
            name = names_dict[target] # Look up the proper name for this page in the names dictionary
            return '<a href="{0}">{1}</a>'.format(create_link(target), name)

        # If we need to change the output tag name
        text = ''
        if element.tag == 'c':
            tag = 'kbd'
        else:
            tag = element.tag

        # Only add outer tags if we're not at the top level of the tree -
        # we don't want <description> and friends in our html
        if not _toplevel:
            text += '<{}>'.format(tag)
        if element.text:
            text += element.text
        for child in element:
            text += convert_hypertext(child, _toplevel=False)
            if child.tail:
                text += child.tail
        if not _toplevel:
            text += '</{}>'.format(tag)
        return text 
    return convert_hypertext

def format_code(code):
    return '\n' + code.strip()

class ReferenceItem:
    '''Represents a single page of reference information.'''
    def __init__(self, source_xml):
        print("Parsing", source_xml)
        xml = etree.parse(source_xml)
        if xml.find('name') is not None:
            self.name = xml.find('name').text
        if xml.find('type') is not None:
            self.type = xml.find('type').text
        if xml.find('example') is not None:
            self.examples = []
            for example in xml.iterfind('example'):
                self.examples.append({'code': format_code(example.find('code').text), 'image':example.find('image') is not None}) 
        if xml.find('description') is not None:
            self.description = xml.find('description')
        if xml.find('syntax') is not None:
            self.syntax = xml.find('syntax')
        if xml.find('parameter') is not None:
            self.parameters = []
            for parameter in xml.iterfind('parameter'):
                label = parameter.find('label').text
                description = parameter.find('description')
                self.parameters.append({'label':label, 'description':description})
        if xml.find('method') is not None:
            self.methods = []
            for method in xml.iterfind('method'):
                label = method.find('label').text
                description = method.find('description')
                ref = create_link(method.find('ref').text)
                self.methods.append({'label':label, 'description':description, 'ref':ref})
        if xml.find('constructor') is not None:
            self.constructors = []
            for constructor in xml.iterfind('constructor'):
                self.constructors.append(constructor.text)
        if xml.find('related') is not None:
            self.relateds = []
            for related in xml.iterfind('related'):
                self.relateds.append(related.text)

def print_header(text):
    print('=== \033[95m{}\033[0m ==='.format(text))

def print_error(text):
    print('\033[91mError: {}\033[0m'.format(text))

# A flat name is the name of the file, sans .xml
def get_flat_names_to_update(src_dir, target_dir, all):
    if not all:
        def should_be_updated(f):
            src_f = src_dir + f
            if not f.endswith('.xml'):
                return False
            target_f = '%s/%s.html' % (target_dir, f[:-4])
            if not os.path.exists(target_f):
                return True
            return os.path.getmtime(src_f) > os.path.getmtime(target_f)
        
        files = filter(should_be_updated, os.listdir(src_dir))
    else:
        files = filter(lambda f: f.endswith('.xml'), os.listdir(src_dir))

    files = map(lambda f: f[:-4], files)
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

    # Dictionary from flat names to ReferenceItems
    items_dict = {}
    for filename in os.listdir(src_dir):
        if not filename.endswith('.xml'):
            continue
        items_dict[filename[:-4]] = ReferenceItem(src_dir + filename)
    convert_hypertext = make_convert_hypertext(items_dict)

    to_update = get_flat_names_to_update(src_dir, target_dir, all)
    if one:
        to_update = to_update[0:1]
 
    print('%s stale files to be translated' % len(to_update))

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), trim_blocks='true')
    reference_template = env.get_template("reference_item_template.jinja")

    start = datetime.datetime.now()
    today = start.ctime()

    whitespace = re.compile(r'^\s+$')

    for flat_name in to_update:
        source_file_path = src_dir + flat_name + '.xml'
        target_file_path = target_dir + flat_name + '.html'
        print("Rendering {} to {}...".format(source_file_path, target_file_path))
        source_item = items_dict[flat_name]
        with open(target_file_path, 'w') as target_file:
            rendered = reference_template.render(item=source_item, today=today, items_dict=items_dict, convert_hypertext=convert_hypertext, create_link=create_link)
            rendered_tree = lxml.html.fromstring(rendered)
            for element in rendered_tree.iter():
                if element.text is not None and whitespace.match(element.text):
                    element.text = None
                if element.tail is not None and whitespace.match(element.tail):
                    element.tail = None
            target_file.write(lxml.html.tostring(rendered_tree, encoding='unicode').encode('utf-8'))
            print("Success.")

    print('Copying static resources...')
    distutils.dir_util.copy_tree('./content', target_dir)
    print('Done.')
    timedelta = datetime.datetime.now() - start
    print('Build took {} seconds'.format(timedelta.seconds + timedelta.microseconds/1000000))

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
