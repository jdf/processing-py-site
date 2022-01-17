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
import cgi
import time, datetime

import jinja2
import lxml.html
from lxml import etree # We need to use lxml because it can handle CDATA tags

src_dir='.'
target_dir=os.path.join(src_dir, 'generated/')

# Names to use in links
canon_reference_dir = '/reference/'
canon_tutorials_dir = '/tutorials/'
canon_cover_dir = '/'
canon_examples_dir = '/examples/'

# Names to use during file manipulation
target_reference_dir = target_dir + canon_reference_dir
target_tutorials_dir = target_dir + canon_tutorials_dir
target_cover_dir     = target_dir + canon_cover_dir
target_examples_dir  = target_dir + canon_examples_dir
reference_dir='Reference/api_en/'
tutorials_dir='Tutorials/'

# files in the reference matching these regexps will not be built or included
# in the index.
to_skip_patterns = [
    r'^PShape.*',
    r'^PrintWriter.*',
    r'^Table.*',
    r'^beginRecord',
    r'^endRecord',
    r'^loadTable$',
    r'^saveTable',
]

def print_header(text):
    print('=== \033[35m{}\033[0m ==='.format(text))

def print_error(text):
    print('\033[31m{}\033[0m'.format(text))

def print_warning(text):
    print('\033[33m{}\033[0m'.format(text))

def print_success(text):
    print('\033[32m{}\033[0m'.format(text))

class ReferenceItem:
    '''Represents a single page of reference information.'''
    def __init__(self, source_xml):
        self.source_xml = source_xml
        xml = etree.parse(source_xml)

        self.name = None
        if xml.find('name') is not None:
            self.name = self.get_element_text(xml.find('name'))

        self.type = None
        if xml.find('type') is not None:
            self.type = self.get_element_text(xml.find('type'))
        
        self.description = None
        if xml.find('description') is not None:
            self.description = xml.find('description')

        self.syntax = None
        if xml.find('syntax') is not None:
            self.syntax = xml.find('syntax')

        self.category = None
        if xml.find('category') is not None:
            self.category = self.get_element_text(xml.find('category'))

        self.subcategory = None
        if xml.find('subcategory') is not None:
            self.subcategory = self.get_element_text(xml.find('subcategory'))

        self.usage = None
        if xml.find('usage') is not None:
            self.usage = self.get_element_text(xml.find('usage'))

                  
        # We store plain xml-elements for some children so that we can use convert_hypertext on them at generation time.
        # This is necessary because all ReferenceItems have to be parsed before links can be resolved.
        self.examples = []
        # Note: 'image' starts out as a flag representing whether this example wants an image or not.
        # It is later transformed into the url of the image we've generated.
        for example in xml.iterfind('example'):
            self.examples.append({
                'code':   self.get_element_text(example.find('code')),
                'image':  example.find('image') is not None,
                'run':    example.find('notest') is None
                })
 
        self.parameters = []
        for parameter in xml.iterfind('parameter'):
            label = self.get_element_text(parameter.find('label'))
            description = parameter.find('description')
            self.parameters.append({'label':label, 'description':description})
        
        self.methods = []
        for method in xml.iterfind('method'):
            label = self.get_element_text(method.find('label'))
            description = method.find('description')
            ref = create_ref_link(self.get_element_text(method.find('ref')))
            self.methods.append({'label':label, 'description':description, 'ref':ref})

        self.constructors = []
        for constructor in xml.iterfind('constructor'):
            self.constructors.append(self.get_element_text(constructor))

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

export_image_postlude = r'''
save('{imagefile}')
exit()
'''

# run an instance of generate_images.py, capturing and recording its output.
# base_cmd should be a list-formatted command-line to run the
# generate_images.py script, suitable for passing to subprocess.Popen;
# workitems should be a list of dictionaries describing the scripts to be run.
def image_worker(base_cmd, workitems):

    workitems_cmdline_param = ['{}:{}:{}'.format(ex['name'], ex['scriptfile'], ex['imagefile']) \
            for ex in workitems.itervalues()]
    process = subprocess.Popen(base_cmd + workitems_cmdline_param, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1)
    generated = {}
    failed = {}
    current = None

    for line in iter(process.stdout.readline, ''):
        m = re.search(r'^:RUNNING:(.+)$', line)
        if m:
            current = workitems[m.group(1)]
            print("{} ... RUNNING: {}".format('Image process', current['name']))
            continue
        m = re.search(r'^:SUCCESS:$', line)
        if m:
            print("{} ... SUCCESS: ".format('Image process'), end='')
            print_success("{} -> {}".format(current['name'], current['imagefile']))
            generated[current['name']] = current
            current = None
            continue
        m = re.search(r'^:FAILURE:$', line)
        if m:
            print("{} ... FAILURE: ".format('Image process'), end='')
            print_error(current['name'])
            failed[current['name']] = current
            current = None
            continue
        # Not a success or failure, must be debug messages
        print("{} ... DEBUG: {}".format('Image process', line), end='')

    process.wait()
    if process.returncode == 0:
        print("Image process terminated successfully.")
    else:
        print_error("Image process terminated unsuccessfully.")
        if current:
            failed[current['name']] = current
        # if the process just plain exited without doing anything,
        # add a sentinel value so it "counts" as an error in the calling
        # code (FIXME this is a hack)
        if len(failed) == 0:
            failed['PROBLEM'] = {'name': 'problem'}
    return generated, failed

def generate_images(items_dict, to_update, src_dir, processing_py_jar,
        target_image_dir, javabin="java"):
    '''Generate images from examples and return the number of failures.'''
    workitems  = {} # Examples to run
    work_dir   = tempfile.mkdtemp(prefix='processing-py-site-build')
    generate_img_script = os.path.join(src_dir, 'jython', 'generate_images.py')
    if not os.path.exists(generate_img_script):
        raise IOError("{} doesn't exist; can't generate images.".format(generate_img_script))

    for name in to_update:
        item = items_dict[name]
        for number, example in enumerate(item.examples):
            if not example['run']:
                # This is an interactive sketch we can't run; ignore it
                continue
            workitem = {}
            workitem['name'] = name + str(number)
            workitem['scriptfile'] = os.path.join(work_dir, workitem['name'] + '.py')
            workitem['imagefile'] = os.path.join(target_image_dir, workitem['name'] + '.png')
            workitem['code']= example['code'] + export_image_postlude.format(imagefile=workitem['imagefile'])
            with open(workitem['scriptfile'], 'w') as f:
                f.write(workitem['code'])
            workitems[workitem['name']] = workitem # We store workitems by name; a little redundant, but handy

    if len(workitems) == 0:
        print("Skipping image generation, everything up to date") 
        return 0

    base_cmd = [javabin, "-cp", processing_py_jar, "org.python.util.jython",
            generate_img_script, '--todo']

    # TODO: use the multiprocessing module's Pool class to run multiple
    # instances of this at once
    generated, failed = image_worker(base_cmd, workitems) 

    print("Generated images:")
    for workitem in generated.itervalues():
        print("    ", workitem['imagefile'])

    print("Failed examples:")
    for workitem in failed.itervalues():
        print("    ", workitem['name'])
    
    print("Done rendering examples.")
    return len(failed)

def find_images(items_dict, to_update, img_dir):
    for name in to_update:
        item = items_dict[name]
        for number, example in enumerate(item.examples):
            example_filename = name + str(number) + '.png'
            example_path = os.path.join(img_dir, example_filename)
            if example['image']:
                if os.path.exists(example_path):
                    # UPDATE THIS if the image directory changes!
                    example['image'] = canon_reference_dir + 'imgs/' + example_filename
                else:
                    # We want an image, but we don't have one. hm.
                    del example['image']
                    if example['run']:
                        example['broken'] = True
            else:
                if os.path.exists(example_path):
                    # So, we run all example sketches as a kind of unit-test, and they all save images,
                    # but some of those images don't actually need to be drawn. This is one of those
                    # images.
                    os.remove(example_path)

def make_convert_hypertext(names_dict):
    """
    Create a function to convert etree.Elements from our source xml into properly-formatted HTML.
    The function is used directly from jinja.
    """
    def convert_hypertext(element, _toplevel=True):
        if element is None:
            return ''
            
        if _toplevel:
            element = copy.deepcopy(element)
            text = element.text if hasattr(element, 'text') and element.text else ''

        if hasattr(element, 'tag') and element.tag == 'ref':
            element.tag = 'a'
            name = names_dict[target] # Look up the proper name for this page in the names dictionary
            element.attib['href'] = create_ref_link(target)
            element.text = name
        elif hasattr(element, 'tag') and element.tag == 'c':
            element.tag = 'kbd'

        for child in element:
            convert_hypertext(child, _toplevel=False)
            if _toplevel:
                # We don't just do this at the top level because we need to skip the top-level tags
                s = lxml.html.tostring(child)
                if s:
                    text += s

        if _toplevel:
            return text

    return convert_hypertext

def clean_html(html):
    html_tree = lxml.html.fromstring(html)
    return lxml.html.tostring(html_tree, encoding='ascii')

def create_ref_link(name):
    return canon_reference_dir + name + '.html' # We might change this later

def build_reference(reference_dir, to_update, env, build_images):
    print('Building reference')
    if not to_update:
        print_success('Nothing to do.')
        return 0 
    failures = 0
    # Dictionary from flat names to ReferenceItems
    items_dict = {}
    for filename in os.listdir(reference_dir):
        if not filename.endswith('.xml'):
            continue
        items_dict[filename[:-4]] = ReferenceItem(os.path.join(reference_dir, filename))
    items_dict[''] = items_dict['blank'] # Special case, for blank links

    print_success('{} stale files to be updated'.format(len(to_update)))

    target_img_dir = os.path.join(target_reference_dir, 'imgs')
    if not os.path.exists(target_reference_dir):
        os.makedirs(target_reference_dir)
    if not os.path.exists(target_img_dir):
        os.makedirs(target_img_dir)

    if build_images:
        failures += generate_images(items_dict, to_update, src_dir, "./processing-py.jar", target_img_dir)
    find_images(items_dict, to_update, target_img_dir)

    reference_template = env.get_template("reference_item_template.jinja")
    convert_hypertext = make_convert_hypertext(items_dict)

    env.globals['items_dict'] = items_dict
    env.globals['convert_hypertext'] = convert_hypertext
    env.globals['create_ref_link'] = create_ref_link
    env.globals['hasattr'] = hasattr

    for flat_name in to_update:
        source_file_path = os.path.join(reference_dir, flat_name + '.xml')
        target_file_path = os.path.join(target_reference_dir, flat_name + '.html')
        print("Rendering {} to {}... ".format(source_file_path, target_file_path), end='')
        source_item = items_dict[flat_name]
        with open(target_file_path, 'w') as target_file:
            rendered = reference_template.render(item=source_item, today=datetime.datetime.now().ctime())
            target_file.write(clean_html(rendered))
            print_success('success!')
    return failures
 
def build_reference_index(reference_dir, env):
    import re
    print('Building reference index')
    reference_items = list()
    for filename in os.listdir(reference_dir):
        if not filename.endswith('.xml'): continue
        item = ReferenceItem(os.path.join(reference_dir,filename))
        item.flatname = os.path.basename(filename)[:-4]
        if any([re.search(pattern, item.flatname) for pattern in to_skip_patterns]):
            print("skipping %s" % filename)
            continue
        reference_items.append(item)
    categories = dict()
    for item in reference_items:
        path = (item.category, getattr(item, 'subcategory', ""))
        if path == ('', ''): continue
        # Fields and Methods aren't included in the index
        if path[1] in ('Method', 'Field'): continue
        if path not in categories:
            categories[path] = list()
        categories[path].append(item)
    category_order = [
        ('Structure', ''),
        ('Environment', ''),
        ('Data', 'Primitive'),
        ('Data', 'Composite'),
        ('Data', 'Conversion'),
        ('Data', 'Dictionary Methods'),
        ('Data', 'List Methods'),
        ('Data', 'String Methods'),
        ('Data', 'List Functions'),
        ('Data', 'String Functions'),
        ('Control', 'Relational Operators'),
        ('Control', 'Iteration'),
        ('Control', 'Conditionals'),
        ('Control', 'Logical Operators'),
        ('Shape', ''),
        ('Shape', '2D Primitives'),
        ('Shape', 'Curves'),
        ('Shape', '3D Primitives'),
        ('Shape', 'Attributes'),
        ('Shape', 'Vertex'),
        ('Shape', 'Loading & Displaying'),
        ('Input', 'Mouse'),
        ('Input', 'Keyboard'),
        ('Input', 'Files'),
        ('Input', 'Time & Date'),
        ('Output', 'Text Area'),
        ('Output', 'Image'),
        ('Output', 'Files'),
        ('Transform', ''),
        ('Lights, Camera', 'Lights'),
        ('Lights, Camera', 'Camera'),
        ('Lights, Camera', 'Coordinates'),
        ('Lights, Camera', 'Material Properties'),
        ('Color', 'Setting'),
        ('Color', 'Creating & Reading'),
        ('Image', ''),
        ('Image', 'Loading & Displaying'),
        ('Image', 'Textures'),
        ('Image', 'Pixels'),
        ('Rendering', ''),
        ('Rendering', 'Shaders'),
        ('Typography', ''),
        ('Typography', 'Loading & Displaying'),
        ('Typography', 'Attributes'),
        ('Typography', 'Metrics'),
        ('Math', 'PVector'),
        ('Math', 'Operators'),
        ('Math', 'Bitwise Operators'),
        ('Math', 'Calculation'),
        ('Math', 'Trigonometry'),
        ('Math', 'Random'),
        ('Constants', ''),
    ]
    assert set(category_order) == set(categories.keys()), \
            "category order and category keys are different. " + \
            str(set(category_order) - set(categories.keys())) + " *** " + \
            str(set(categories.keys()) - set(category_order))
    elements = list()
    current_cat = None
    current_subcat = None
    for path in category_order:
        cat, subcat = path
        if cat != current_cat:
            if current_cat is not None:
                elements.append({'type': 'end-category', 'content': None})
            elements.append({'type': 'start-category', 'content': cat})
            current_cat = cat
        if subcat != current_subcat:
            if current_subcat is not None:
                elements.append({'type': 'end-subcategory', 'content': None})
            elements.append({'type': 'start-subcategory', 'content': subcat})
            current_subcat = subcat
        elements.append({'type': 'start-list', 'content': None})
        for item in sorted(categories[path], key=lambda x: x.name):
            elements.append({'type': 'link', 'content': item})
        elements.append({'type': 'end-list', 'content': None})
    elements.append({'type': 'end-subcategory', 'content': None})
    elements.append({'type': 'end-category', 'content': None})

    index_template = env.get_template('reference_index_template.jinja')
    with open(os.path.join('generated/reference', 'index.html'), 'w') as tfile:
        tfile.write(clean_html(index_template.render(elements=elements)))
    print_success('success!')

def build_tutorials(env):
    print('Building tutorials')
    item_template = env.get_template('tutorial_item_template.jinja')
    index_template = env.get_template('tutorial_index_template.jinja')
    index_data = etree.parse(os.path.join(tutorials_dir, 'tutorials.xml'))
    tutorials = []
    for tutorial_element in index_data.iterfind('tutorial'):
        tutorial = {}
        tutorial['folder'] = tutorial_element.text
        tutorial['url'] = canon_tutorials_dir + tutorial['folder']
        print('Handling tutorial {}... '.format(tutorial['folder']), end='')
        tutorial_data = etree.parse(os.path.join(tutorials_dir, tutorial['folder'], 'tutorial.xml'))
        tutorial['image'] = os.path.join(tutorial['folder'], 'imgs', tutorial_data.find('image').text)
        tutorial['title'] = tutorial_data.find('title').text
        tutorial['author'] = tutorial_data.find('author').text
        tutorial['blurb'] = tutorial_data.find('blurb')
        # I want to use convert_hypertext on the examples so they can use things like 'ref';
        # we can use lxml.html to parse the html into an element-tree!
        # Note that even though the index.html files don't have <html> or <body> tags, lxml.html automatically creates nodes for them.
        content = lxml.html.parse(os.path.join(tutorials_dir, tutorial['folder'], 'index.html'))
        tutorial['content'] = content.getroot().find('body')
        target_tutorial_dir = os.path.join(target_tutorials_dir, tutorial['folder'])
        if not os.path.exists(target_tutorial_dir):
            os.makedirs(target_tutorial_dir)
        with open(os.path.join(target_tutorial_dir, 'index.html'), 'w') as target_file:
            target_file.write(clean_html(item_template.render(tutorial=tutorial)))
        target_img_dir = os.path.join(target_tutorial_dir, 'imgs')
        if os.path.exists(target_img_dir):
            shutil.rmtree(target_img_dir)
        shutil.copytree(os.path.join(tutorials_dir, tutorial['folder'], 'imgs'), target_img_dir)
        tutorials.append(tutorial)
        print_success('success!')
    print('Building tutorial index page... ', end='')
    with open(os.path.join(target_tutorials_dir, 'index.html'), 'w') as target_file:
        target_file.write(clean_html(index_template.render(tutorials=tutorials)))
    print_success('success!')

def build_examples(env):
    print("building examples")
    if not os.path.exists(target_examples_dir):
        os.makedirs(target_examples_dir)
    examples_template = env.get_template('examples_index.jinja')
    with open(os.path.join(target_examples_dir, 'index.html'), 'w') as tfile:
        tfile.write(clean_html(examples_template.render()))
    print_success('success!')

def build_cover(env):
    print("building index.html")
    cover_template = env.get_template('index.jinja')
    with open(os.path.join('generated', 'index.html'), 'w') as tfile:
        tfile.write(clean_html(cover_template.render()))
    print_success('success!')

def build(build_images, to_update):
    print_header("Building content")

    reference_dir = os.path.join(src_dir, 'Reference', 'api_en')
    tutorials_dir = os.path.join(src_dir, 'Tutorials')
    content_dir = os.path.join(src_dir, 'content')
    template_dir = os.path.join(src_dir, 'template')
    
    start = datetime.datetime.now()
    failures = 0

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    if not os.path.exists(reference_dir):
        print_error("Can't find {}; please don't change the format of the repo on me.".format(reference_dir))
        sys.exit(1)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), trim_blocks='true')
    
    failures += build_reference(reference_dir, to_update, env, build_images)
    build_tutorials(env)
    build_reference_index(reference_dir, env)
    build_cover(env)
    build_examples(env)
       
    print('Copying static resources...')
    distutils.dir_util.copy_tree('./content', target_dir)
    print('Done.')
    timedelta = datetime.datetime.now() - start
    print('Build took {} seconds'.format(timedelta.seconds + timedelta.microseconds/1000000))
    if failures:
        print_error('{} failure(s)'.format(failures))
        sys.exit(1)

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

# A flat name is the name of the file, sans .xml
def get_flat_names_to_update(all_, random, files):

    if files:
        # print_error() returns None, which is falsy, and so can be used to filter!
        # ...this is silly
        files = filter(lambda f: f if f.endswith('.xml') else print_error('"{}" is not a valid xml file!'.format(f)), files)
        return map(lambda f: os.path.basename(f)[:-4], files)

    if random:
        return [map(lambda f: f[:-4], filter(lambda f: f.endswith('.xml'), os.listdir(reference_dir)))[0]]

    if not all_:
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

    # skip files that match patterns in to_skip_patterns
    files = [f for f in files if not(any([re.search(patt, f) for patt in to_skip_patterns]))]
    files = map(lambda f: f[:-4], files)
    return files

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
    build_type = build_parser.add_mutually_exclusive_group()
    build_type.add_argument('--all', action='store_true', help='Build all pages')
    build_type.add_argument('--random', action='store_true', help='Build an arbitrary file (for testing purposes)')
    build_type.add_argument('--files', nargs='+', help='Build a specific set of files')
    build_parser.add_argument('--images', action='store_true', help="Run and save example sketches")
    test_parser = subparsers.add_parser('test', description='Test locally')
    clean_parser = subparsers.add_parser('clean', description='Clean generated stuff')
    args = parser.parse_args()

    proper_dir = os.path.dirname(os.path.realpath(__file__))
    if not os.path.samefile(os.path.realpath(os.getcwd()), proper_dir):
        print_warning('Changing to proper working directory: {}'.format(proper_dir))
        os.chdir(proper_dir)

    depends_dir = os.path.realpath('./depends')

    if args.command == 'build':
        build(build_images=args.images, to_update=get_flat_names_to_update(all_=args.all, random=args.random, files=args.files))
    elif args.command == 'test':
        test()
    elif args.command == 'clean':
        shutil.rmtree(target_dir)
