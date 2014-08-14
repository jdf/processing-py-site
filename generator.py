#!/usr/bin/env python
from __future__ import division, with_statement, print_function
from argparse import ArgumentParser
from cStringIO import StringIO

import threading
import subprocess
import tempfile
import os
import re
import shutil
import distutils.core
import sys
import copy
import time, datetime

try:
    import jinja2
    import lxml.html
    from lxml import etree # We need to use lxml because it can handle CDATA tags
except:
    print("I can't import my dependencies for some reason.")
    print("Please run pip install -r requirements.txt before using generator.py.")
    sys.exit(1)

def print_header(text):
    print('=== \033[35m{}\033[0m ==='.format(text))

def print_error(text):
    print('\033[31m{}\033[0m'.format(text))

def print_warning(text):
    print('\033[32m{}\033[0m'.format(text))

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

def get_element_text(element):
    '''Get element.text, supplying the empty string if element.text is None'''
    text = element.text
    if text is None:
        print_warning("Warning: Element '{}' has no text".format(element.tag))
        text = ''
    return text

class ReferenceItem:
    '''Represents a single page of reference information.'''
    def __init__(self, source_xml):
        print("Parsing", source_xml)
        xml = etree.parse(source_xml)
        if xml.find('name') is not None:
            self.name = get_element_text(xml.find('name'))
        if xml.find('type') is not None:
            self.type = get_element_text(xml.find('type'))
        if xml.find('example') is not None:
            self.examples = []
            for example in xml.iterfind('example'):
                self.examples.append({'code': format_code(get_element_text(example.find('code'))), 'image':example.find('image') is not None}) 

        # We store plain xml-elements for some children so that we can use convert_hypertext on them at generation time.
        # This is necessary because all ReferenceItems have to be parsed before links can be resolved.
        if xml.find('description') is not None:
            self.description = xml.find('description')
        if xml.find('syntax') is not None:
            self.syntax = xml.find('syntax')
        if xml.find('parameter') is not None:
            self.parameters = []
            for parameter in xml.iterfind('parameter'):
                label = get_element_text(parameter.find('label'))
                description = parameter.find('description')
                self.parameters.append({'label':label, 'description':description})
        if xml.find('method') is not None:
            self.methods = []
            for method in xml.iterfind('method'):
                label = get_element_text(method.find('label'))
                description = method.find('description')
                ref = create_link(get_element_text(method.find('ref')))
                self.methods.append({'label':label, 'description':description, 'ref':ref})
        if xml.find('constructor') is not None:
            self.constructors = []
            for constructor in xml.iterfind('constructor'):
                self.constructors.append(get_element_text(constructor))
        if xml.find('related') is not None:
            self.relateds = []
            for related in xml.iterfind('related'):
                self.relateds.append(get_element_text(related))

def make_jython_command(processing_py_dir):
    dist_dir = os.path.join(processing_py_dir, 'dist')
    if not os.path.exists(dist_dir):
       raise IOError("{} does not exist. Please run 'ant make-all-distributions' in the processing.py dir to make something I can use.".format(dist_dir))
    import platform
    system = platform.system()
    if 'Darwin' in system:
        system_string = 'macosx'
    elif 'Linux' in system:
        arch, _ = platform.architecture()
        if '64' in arch:
            system_string = 'linux64'
        else:
            system_string = 'linux32'
    elif 'Java' in system:
        raise RuntimeError('Please run generator.py with python rather than jython.')
    elif 'Windows' in system:
        raise RuntimeError('Building (examples) is not supported on Windows.')
    else:
        raise RuntimeError("Don't know what system we're on.")

    # Find most-recent processing.py distribution folder for current platform
    platform_dist_dir = sorted(filter(lambda f: f.endswith(system_string), os.listdir(dist_dir)))[0]
    platform_dist_dir = os.path.join(dist_dir, platform_dist_dir)
    javabin = os.path.join(platform_dist_dir, 'jre', 'bin', 'java')
    jars = filter(lambda f: f.endswith('.jar'), os.listdir(platform_dist_dir))
    classpath = ''
    for jar in jars:
        classpath += os.path.join(platform_dist_dir, jar) + ':'
    classpath = classpath[:-1]
    return [javabin, '-cp', classpath, 'org.python.util.jython']

class JythonImageProcess:
    success_re = re.compile(r'^SUCCESS:([^:]+):(.+)$')
    failure_re = re.compile(r'^FAILURE:(.+)$')

    @staticmethod
    def consume_communication(fd, desc, generated):
        for line in iter(fd.readline, ''):
            success = JythonImageProcess.success_re.match(line)
            if success:
                print("{} ... SUCCESS: {} -> {}".format(desc, success.group(1), success.group(2)))
                generated.add(success.group(2))
                continue
            failure = JythonImageProcess.failure_re.match(line)
            if failure:
                print_error("{} ... FAILURE: {}".format(desc, failure.group(1)))
                continue
            print_error("{} ... Failed to parse output: {}".format(desc, line))
    
    @staticmethod
    def consume_debug(fd, desc):
        for line in iter(fd.readline, ''):
            print("{} ... {}".format(desc, line), end='')

    def __init__(self, p5py_dir, jython_dir, examples_dir, target_dir):
        self.generated = set()
        jython_script = os.path.join(jython_dir, 'generate_images.py')
        if not os.path.exists(jython_script):
            raise IOError("{} doesn't exist; can't generate images.")
        args = make_jython_command(p5py_dir) + [jython_script, examples_dir, target_dir]
        self.popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1) # line-buffered
        self.comthread = threading.Thread(target=JythonImageProcess.consume_communication, args=(self.popen.stdout, self.desc(), self.generated))
        self.comthread.start()
        self.debugthread = threading.Thread(target=JythonImageProcess.consume_debug, args=(self.popen.stderr, self.desc()))
        self.debugthread.start()
 
    def is_complete(self):
        return self.popen.poll() != None

    def exited_well(self):
        return self.popen.returncode == 0

    def print_debug(self):
        print("Debug from {}:".format(self.desc()))
        for line in self.err_blob:
            print("{}: {}".format(self.desc(), line))

    def desc(self):
        return self.popen.pid

# A flat name is the name of the file, sans .xml
def get_flat_names_to_update(reference_dir, target_dir, all):
    if not all:
        def should_be_updated(f):
            src_f = os.path.join(reference_dir, f)
            if not f.endswith('.xml'):
                return False
            target_f = os.path.join(target_dir, f[:-4] + '.html')
            if not os.path.exists(target_f):
                return True
            return os.path.getmtime(src_f) > os.path.getmtime(target_f)
        
        files = filter(should_be_updated, os.listdir(reference_dir))
    else:
        files = filter(lambda f: f.endswith('.xml'), os.listdir(reference_dir))

    files = map(lambda f: f[:-4], files)
    return files

def render_templates(items_dict, to_update, src_dir, reference_dir, target_dir):
    template_dir = os.path.join(src_dir, 'template')
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), trim_blocks='true')
    reference_template = env.get_template("reference_item_template.jinja")
    convert_hypertext = make_convert_hypertext(items_dict)

    env.globals['items_dict'] = items_dict
    env.globals['convert_hypertext'] = convert_hypertext
    env.globals['create_link'] = create_link
    env.globals['hasattr'] = hasattr

    whitespace = re.compile(r'^\s+$')

    for flat_name in to_update:
        source_file_path = os.path.join(reference_dir, flat_name + '.xml')
        target_file_path = os.path.join(target_dir, flat_name + '.html')
        print("Rendering {} to {}... ".format(source_file_path, target_file_path), end='')
        source_item = items_dict[flat_name]
        with open(target_file_path, 'w') as target_file:
            rendered = reference_template.render(item=source_item, today=datetime.datetime.now().ctime())
            rendered_tree = lxml.html.fromstring(rendered)
            for element in rendered_tree.iter():
                if element.text is not None and whitespace.match(element.text):
                    element.text = None
                if element.tail is not None and whitespace.match(element.tail):
                    element.tail = None
            target_file.write(lxml.html.tostring(rendered_tree, encoding='unicode').encode('utf-8'))
            print('success')

def generate_images(items_dict, to_update, src_dir, target_dir, p5py_dir, worker_processes=4):
    examples = set()
    for name in to_update:
        try:
            item = items_dict[name]
            for number, example in enumerate(item.examples):
                examples.add((name + str(number), example['code']))
        except AttributeError:
            pass
    if len(examples) == 0:
        print("Skipping image generation, no examples to parse") 
        return
    if len(examples) < worker_processes:
        worker_processes = 1

    # Some simple, probably uneven work distribution
    workloads = []
    for _ in range(worker_processes):
        workloads.append(set())
    workload_index = 0
    for example in examples:
        workloads[workload_index].add(example)
        workload_index = (workload_index + 1) % worker_processes
    
    workload_dirs = set()
    for workload in workloads:
        workload_dir = tempfile.mkdtemp(prefix='processing-py-site-build')
        for example in workload:
            name, source = example
            with open(os.path.join(workload_dir, name + '.py'), 'w') as f:
                f.write(source)
        workload_dirs.add(workload_dir)

    jython_dir = os.path.join(src_dir, 'jython')
    if not os.path.exists(jython_dir):
        raise IOError("{} doesn't exist; can't generate images.".format(jython_dir))

    processes = set()
    for workload_dir in workload_dirs:
        processes.add(JythonImageProcess(p5py_dir, jython_dir, workload_dir, target_dir))

    generated = set()

    while processes:
        for process in processes.copy():
            if process.is_complete():
                if process.exited_well():
                    print("Process {} terminated successfully.".format(process.desc()))
                else:
                    print_error("Process {} terminated unsuccessfully.".format(process.desc()))
                generated &= process.generated
                processes.remove(process)
        time.sleep(0.2)

    print("Generated images:")
    for image in generated:
        print("    ", image)

def build(src_dir='.', target_dir='./generated/', p5py_dir='../processing.py', all=False, one=False, images=True):
    print_header("Building content")
    
    reference_dir = os.path.join(src_dir, 'Reference', 'api_en')
    content_dir = os.path.join(src_dir, 'content')
    start = datetime.datetime.now()

    if one:
        shutil.rmtree(target_dir)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    if not os.path.exists(reference_dir):
        print('Go to the root of the repo for now, please')
        sys.exit(1)

    # Dictionary from flat names to ReferenceItems
    items_dict = {}
    for filename in os.listdir(reference_dir):
        if not filename.endswith('.xml'):
            continue
        items_dict[filename[:-4]] = ReferenceItem(os.path.join(reference_dir, filename))
    items_dict[''] = items_dict['blank'] # Special case, for blank links

    to_update = get_flat_names_to_update(reference_dir, target_dir, all)
    if one:
        to_update = to_update[0:1]
 
    print('{} stale files to be updated'.format(len(to_update)))
    
    if images:
        generate_images(items_dict, to_update, src_dir, target_dir, p5py_dir, worker_processes=4)

    render_templates(items_dict, to_update, src_dir, reference_dir, target_dir)
    
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
    build_parser.add_argument('--noimages', action='store_true', help="Don't run any example sketches")
    build_parser.add_argument('--p5py', default='../processing.py', help='Set location of processing.py installation')
    test_parser = subparsers.add_parser('test', description='Test locally')
    args = parser.parse_args()
    if args.command == 'build':
        build(all=args.all, one=args.one, images=not args.noimages)
    elif args.command == 'test':
        test()
