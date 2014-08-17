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

bootstrapped = True

try:
    import jinja2
    import lxml.html
    from lxml import etree # We need to use lxml because it can handle CDATA tags
except:
    bootstrapped = False


src_dir='.'
target_dir='./generated/'
reference_dir='./Reference/api_en/'


def print_header(text):
    print('=== \033[35m{}\033[0m ==='.format(text))

def print_error(text):
    print('\033[31m{}\033[0m'.format(text))

def print_warning(text):
    print('\033[33m{}\033[0m'.format(text))

def print_success(text):
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

class ReferenceItem:
    '''Represents a single page of reference information.'''
    def __init__(self, source_xml):
        self.source_xml = source_xml
        xml = etree.parse(source_xml)
        if xml.find('name') is not None:
            self.name = self.get_element_text(xml.find('name'))
        if xml.find('type') is not None:
            self.type = self.get_element_text(xml.find('type'))
        if xml.find('example') is not None:
            self.examples = []
            # Note: 'image' starts out as a flag representing whether this example wants an image or not.
            # It is later transformed into the url of the image we've generated.
            for example in xml.iterfind('example'):
                self.examples.append({'code': format_code(self.get_element_text(example.find('code'))), 'image':example.find('noimage') is None})
        # We store plain xml-elements for some children so that we can use convert_hypertext on them at generation time.
        # This is necessary because all ReferenceItems have to be parsed before links can be resolved.
        if xml.find('description') is not None:
            self.description = xml.find('description')
        if xml.find('syntax') is not None:
            self.syntax = xml.find('syntax')
        if xml.find('parameter') is not None:
            self.parameters = []
            for parameter in xml.iterfind('parameter'):
                label = self.get_element_text(parameter.find('label'))
                description = parameter.find('description')
                self.parameters.append({'label':label, 'description':description})
        if xml.find('method') is not None:
            self.methods = []
            for method in xml.iterfind('method'):
                label = self.get_element_text(method.find('label'))
                description = method.find('description')
                ref = create_link(self.get_element_text(method.find('ref')))
                self.methods.append({'label':label, 'description':description, 'ref':ref})
        if xml.find('constructor') is not None:
            self.constructors = []
            for constructor in xml.iterfind('constructor'):
                self.constructors.append(self.get_element_text(constructor))
        if xml.find('related') is not None:
            self.relateds = []
            for related in xml.iterfind('related'):
                self.relateds.append(self.get_element_text(related))

    def get_element_text(self, element):
        '''Get element.text, supplying the empty string if element.text is None. Take filename so we can point to errors.'''
        text = element.text
        if text is None:
            print_warning("Warning: Element '{}' from '{}' has no text".format(element.tag, self.source_xml))
            text = ''
        return text



def check_p5py_platform():
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
    return system_string

class JythonImageProcess:
    '''Class to manage communicating with a remote process. We could eventually have multiple instances going at once.'''
    running_re = re.compile(r'^:RUNNING:(.+)$')
    success_re = re.compile(r'^:SUCCESS:$')
    failure_re = re.compile(r'^:FAILURE:$')
     
    @staticmethod
    def make_jython_command(processing_py_dir):
        dist_dir = os.path.join(processing_py_dir, 'dist')
        if not os.path.exists(dist_dir):
           raise IOError("{} does not exist. Please bootstrap.".format(dist_dir))
        
        system_string = check_p5py_platform()

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
    
    @staticmethod
    def create_args(p5py_dir, jython_dir, workitems):
        command = JythonImageProcess.make_jython_command(p5py_dir)
        jython_script = os.path.join(jython_dir, 'generate_images.py')
        if not os.path.exists(jython_script):
            raise IOError("Can't find jython script to run...")
        command += [jython_script]
        command += ['--todo'] + ['{}:{}:{}'.format(ex['name'], ex['scriptfile'], ex['imagefile']) for ex in workitems.itervalues()]
        return command

    def __init__(self, p5py_dir, jython_dir, workitems):
        self.current = None
        self.generated = {}
        self.failed = {}
        self.workitems = workitems
        args = JythonImageProcess.create_args(p5py_dir, jython_dir, workitems)
        self.popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1) # line-buffered
        self.comthread = threading.Thread(target=self.consume_communication, args=())
        self.comthread.start()

    def consume_communication(self):
        for line in iter(self.popen.stdout.readline, ''):
            running = JythonImageProcess.running_re.match(line)
            if running:
                self.current = self.workitems[running.group(1)]
                print("{} ... RUNNING: {}".format(self.desc, self.current['name']))
                continue
            success = JythonImageProcess.success_re.match(line)
            if success:
                print("{} ... SUCCESS: ".format(self.desc), end='')
                print_success("{} -> {}".format(self.current['name'], self.current['imagefile']))
                self.generated[self.current['name']] = self.current
                self.current = None
                continue
            failure = JythonImageProcess.failure_re.match(line)
            if failure:
                print("{} ... FAILURE: ".format(self.desc), end='')
                print_error(self.current['name'])
                self.failed[self.current['name']] = self.current
                self.current = None
                continue
            # Not a success or failure, must be debug messages
            print("{} ... DEBUG: {}".format(self.desc, line), end='')

    def is_complete(self):
        return self.popen.poll() != None

    def exited_well(self):
        return self.popen.returncode == 0

    def print_debug(self):
        print("Debug from {}:".format(self.desc()))
        for line in self.err_blob:
            print("{}: {}".format(self.desc(), line))

    @property
    def desc(self):
        return 'Image Process'

# A flat name is the name of the file, sans .xml
def get_flat_names_to_update(all, random, files):

    if files:
        # print_error() returns None, which is falsy, and so can be used to filter!
        # ...this is silly
        files = filter(lambda f: f if f.endswith('.xml') else print_error('"{}" is not a valid xml file!'.format(f)), files)
        return map(lambda f: os.path.basename(f)[:-4], files)

    if random:
        return [map(lambda f: f[:-4], filter(lambda f: f.endswith('.xml'), os.listdir(reference_dir)))[0]]

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
            print_success('success!')

export_image_postlude = r'''
save('{imagefile}')
exit()
'''

def generate_images(items_dict, to_update, src_dir, target_dir, p5py_dir):
    workitems  = {} # Examples to run
    work_dir   = tempfile.mkdtemp(prefix='processing-py-site-build')
    jython_dir = os.path.join(src_dir, 'jython')
    if not os.path.exists(jython_dir):
        raise IOError("{} doesn't exist; can't generate images.".format(jython_dir))

    for name in to_update:
        try:
            item = items_dict[name]
            for number, example in enumerate(item.examples):
                workitem = {}
                workitem['name'] = name + str(number)
                workitem['scriptfile'] = os.path.join(work_dir, workitem['name'] + '.py')
                workitem['imagefile'] = os.path.join(target_dir, workitem['name'] + '.png')
                workitem['code']= example['code'] + export_image_postlude.format(imagefile=workitem['imagefile'])
                with open(workitem['scriptfile'], 'w') as f:
                    f.write(workitem['code'])
                workitems[workitem['name']] = workitem # We store workitems by name; a little redundant, but handy
        except AttributeError:
            # item has no examples
            pass

    if len(workitems) == 0:
        print("Skipping image generation, everything up to date") 
        return

    process = None
    generated = {}
    failed = {}

    while workitems:
        if not process:
            print("Starting image process")
            process = JythonImageProcess(p5py_dir, jython_dir, workitems)

        if process.is_complete():
            if process.exited_well():
                print("{} terminated successfully.".format(process.desc))
            else:
                print_error("{} terminated unsuccessfully.".format(process.desc))
                if process.current:
                    process.failed[process.current['name']] = process.current
            for workitem in process.generated.itervalues():
                generated[workitem['name']] = workitem
                del workitems[workitem['name']]
            for workitem in process.failed.itervalues():
                failed[workitem['name']] = workitem
                del workitems[workitem['name']]
            process = None

        time.sleep(0.2)

    print("Generated images:")
    for workitem in generated.itervalues():
        print("    ", workitem['imagefile'])

    print("Failed examples:")
    for workitem in failed.itervalues():
        print("    ", workitem['name'])
    
    print("Done rendering examples.")

def find_images(items_dict, to_update, img_dir):
    for name in to_update:
        try:
            item = items_dict[name]
            for number, example in enumerate(item.examples):
                example_filename = name + str(number) + '.png'
                example_path = os.path.join(img_dir, example_filename)
                if example['image']:
                    if os.path.exists(example_path):
                        # UPDATE THIS if the image directory changes!
                        example['image'] = '/img/{}'.format(example_filename)
                    else:
                        # We want an image, but we don't have one. hm.
                        del example['image']
                        example['broken'] = True
                else:
                    if os.path.exists(example_path):
                        # So, we run all example sketches as a kind of unit-test, and they all save images,
                        # but some of those images don't actually need to be drawn. This is one of those
                        # images.
                        os.remove(example_path)
        except AttributeError:
            pass


def build(images, to_update):
    if not to_update:
        print_error('Nothing to do.')
        sys.exit(0)
    print_header("Building content")
    
    reference_dir = os.path.join(src_dir, 'Reference', 'api_en')
    content_dir = os.path.join(src_dir, 'content')
    start = datetime.datetime.now()

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

    print_success('{} stale files to be updated'.format(len(to_update)))
    
    img_dir = os.path.join(target_dir, 'img')

    if images:
        generate_images(items_dict, to_update, src_dir, os.path.join(target_dir, 'img'), os.path.join(depends_dir, 'processing.py'))
    find_images(items_dict, to_update, img_dir)

    render_templates(items_dict, to_update, src_dir, reference_dir, target_dir)
    
    print('Copying static resources...')
    distutils.dir_util.copy_tree('./content', target_dir)
    print('Done.')
    timedelta = datetime.datetime.now() - start
    print('Build took {} seconds'.format(timedelta.seconds + timedelta.microseconds/1000000))

def test():
    print_header("Testing")
    import random, SimpleHTTPServer, SocketServer, webbrowser
    socket = random.randrange(8000, 8999)
    address = "http://localhost:{}".format(socket)
    print("Serving on {}".format(address)) 
    os.chdir(target_dir)
    httpd = SocketServer.TCPServer(("localhost", socket), SimpleHTTPServer.SimpleHTTPRequestHandler)
    webbrowser.open(address)
    httpd.serve_forever()

def bootstrap(force, dryrun, update):
    if force and os.path.exists(depends_dir):
        shutil.rmtree(depends_dir)

    if dryrun:
        def call(cmd, *args, **kwargs):
            print_warning(' '.join(cmd))
            return True
    else:
        def call(cmd, *args, **kwargs):
            print_warning(' '.join(cmd))
            try:
                return subprocess.call(cmd, *args, **kwargs) == 0 
            except:
                return False

    print_header('Bootstrapping')
    print_warning('(This may take a while.)')
    print('Verifying command requirements...')
    failures = []
    verifiables = [
            ['pip', '-V'],
            ['java','-version'],
            ['javac', '-version'],
            ['ant', '-version'],
            ['git', '--version']
            ]
    for cmd in verifiables:
        if not call(cmd):
            failures.append(cmd[0])

    if failures:
        print_error('Please install/make available the following commands for your platform:')
        for failure in failures:
            print_error('     ' + failure)
        sys.exit(1)

    print_success('All necessary commands supported!')
    
    print('Installing python requirements')
    if not call(['pip', 'install', '-r', 'requirements.txt']):
        print_error("Couldn't install! Oh no!")
        sys.exit(1) 

    if not os.path.exists(depends_dir):
        print('Creating "{}"'.format(depends_dir))
        os.makedirs(depends_dir)

    print('Checking git dependencies...')

    # (repo, url, tag)
    git_repos = [
            ('processing', 'https://github.com/processing/processing.git', 'processing-0227-2.2.1'),
            ('processing-video', 'https://github.com/processing/processing-video.git', None),
            ('processing.py', 'https://github.com/jdf/processing.py.git', None)
            ]

    for repo, url, tag in git_repos:
        repo_path = os.path.join(depends_dir, repo)
        if not os.path.exists(repo_path):
            print('Cloning {}...'.format(repo))
            if tag:
                cmd = ['git', 'clone', '--depth', '1', '--branch', tag, url, repo_path]
            else:
                cmd = ['git', 'clone', '--depth', '1', url, repo_path]
            if not call(cmd):
                print_error('Failed to clone! Oh no!')
                sys.exit(1)

    if update:
        print('Updating dependency repos')
        for repo, url, tag in git_repos: # All guaranteed to exist by now!
            if tag:
                continue # We've checked out a specific tag, no need to update
            repo_path = os.path.join(depends_dir, repo)
            if not call(['git', '--git-dir={}'.format(os.path.join(repo_path, '.git')), '--work-tree={}'.format(repo_path), 'pull']):
                print_error('Failed to pull! Oh no!')
                sys.exit(1)

        print('Cleaning dependencies')
        if not call(['ant', '-buildfile', os.path.join(depends_dir, 'processing.py', 'build.xml'), 'clean']):
            print_error('Clean unsuccessful!')
            sys.exit(1)
    print('Building dependencies')

    # Do these separately to avoid a bug in processing.py/build.xml
    if not call(['ant', '-buildfile', os.path.join(depends_dir, 'processing.py', 'build.xml'), 'build-processing']):
        print_error('Processing build unsuccessful!')
        sys.exit(1)

    if not call(['ant', '-buildfile', os.path.join(depends_dir, 'processing.py', 'build.xml'),
        '-Dplatform={}'.format(check_p5py_platform()), 'make-distribution']):
        print_error('Processing.py build unsuccessful!')
        sys.exit(1)

    print_success('Dependencies good to go!')

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
    build_type = build_parser.add_mutually_exclusive_group(required=True)
    build_type.add_argument('--all', action='store_true', help='Build all pages and examples')
    build_type.add_argument('--random', action='store_true', help='Build an arbitrary file (for testing purposes)')
    build_type.add_argument('--files', nargs='+', help='Build a specific set of files')
    build_parser.add_argument('--images', action='store_true', help="Run and save example sketches")
    test_parser = subparsers.add_parser('test', description='Test locally')
    bootstrap_parser=subparsers.add_parser('bootstrap', description='Verify/download requirements of generator.py')
    bootstrap_parser.add_argument('--force', action='store_true', help='Re-bootstrap even if everything is installed')
    bootstrap_parser.add_argument('--update', action='store_true', help='Update dependencies')
    bootstrap_parser.add_argument('--dryrun', action='store_true', help='Print actions but do not perform them')
    clean_parser = subparsers.add_parser('clean', description='Clean generated stuff')
    args = parser.parse_args()

    proper_dir = os.path.dirname(os.path.realpath(__file__))
    if not os.path.samefile(os.path.realpath(os.getcwd()), proper_dir):
        print_warning('Changing to proper working directory: {}'.format(proper_dir))
        os.chdir(proper_dir)

    depends_dir = os.path.realpath('./depends')

    if not bootstrapped and args.command != 'bootstrap':
        print_error("Please bootstrap, I can't load libraries I need.")

    if args.command == 'build':
        build(images=args.images or args.all, to_update=get_flat_names_to_update(all=args.all, random=args.random, files=args.files))
    elif args.command == 'test':
        test()
    elif args.command == 'bootstrap':
        bootstrap(force=args.force, dryrun=args.dryrun, update=args.update)
    elif args.command == 'clean':
        shutil.rmtree(target_dir)
