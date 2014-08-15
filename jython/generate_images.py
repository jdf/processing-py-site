from __future__ import division, print_function
import sys
import os
import argparse
import re
import traceback

import jarray
import java.lang
import java.util
import java.io

'''Jython script to generate a set of images. Writes output images to stdout and debug messages to stderr.'''

def debug(text):
    print('\033[32mDebug: {}\033[0m'.format(text), file=sys.stderr)

def debug_error():
    for line in traceback.format_exc().splitlines():
        print('\033[31m{}\033[0m'.format(line), file=sys.stderr)

def output_success(filename, result):
    print('SUCCESS:{}:{}'.format(filename, result), file=sys.stdout)

def output_failure(filename):
    print('FAILURE:{}'.format(filename), file=sys.stdout)
    debug('While running {}:'.format(filename))
    debug_error()

try:
    import jycessing.Runner, jycessing.RunnableSketch, jycessing.StreamPrinter
except:
    debug("I can't import the Java code I need to run sketches.")
    debug("Note: don't run this file directly; just use generator.py.")
    sys.exit(1) 

export_image_postlude = r'''
loadPixels()
defaultColor = color(204, 204, 204)
for pixel in pixels:
    if pixel != defaultColor:
        break
    else:
        raise Exception('All pixels default color - this example is pointless!')
save({outputname})
'''

class ExampleImageGenSketch(jycessing.RunnableSketch):
    def __init__(self, filename, source, srcdir, outputdir):
        self.filename = filename
        self.outputname = re.sub(r'$([^.]*)\.py^', r'\1\.png', filename)
        self.srcdir = srcdir
        self.outputdir = outputdir
        self.source = source + export_image_postlude.format(outputname=self.outputname)

    def gen_image(self):
        out_printer = jycessing.StreamPrinter(java.lang.System.err)
        jycessing.Runner.runSketchBlocking(self, out_printer, out_printer)
        return self.outputname

    # Functions to satisfy interface:
    def getMainFile(self):
        return java.io.File(self.filename)

    def getMainCode(self):
        return self.source

    def getHomeDirectory(self):
        return java.io.File(self.srcdir)

    def getPathEntries(self):
        entries = java.util.ArrayList()
        entries.add(java.io.File(self.srcdir))
        return entries

    def getPAppletArguments(self):
        return jarray.array([self.filename], java.lang.String)
    
    def getLibraryDirectories(self):
        dirs = java.util.ArrayList()
        return dirs # TODO what else should we have here?

    def getLibraryPolicy(self):
        return jycessing.Runner.LibraryPolicy.PROMISCUOUS

    def shouldRun(self):
        return 1

def gen(source_dir, target_dir):
    debug('Building from: {}'.format(source_dir))
    for filename in os.listdir(source_dir):
        if not filename.endswith('.py'):
            continue
        filename = os.path.join(source_dir, filename)
        debug('Processing file: {}'.format(filename))
        try:
            with open(filename) as f:
                content = f.read()
            sketch = ExampleImageGenSketch(filename, content, source_dir, target_dir)
            result = sketch.gen_image()
            output_success(filename, result)
        except:
            output_failure(filename)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build a set of images.') 
    parser.add_argument('source_dir')
    parser.add_argument('target_dir')
    args = parser.parse_args()
    try:
       gen(args.source_dir, args.target_dir)
    except:
        debug_error()
        sys.exit(1)
