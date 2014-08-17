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

'''Jython script to generate a set of images.'''

def debug(text):
    print('\033[32m{}\033[0m'.format(text))

def debug_problem(text):
    print('\033[31m{}\033[0m'.format(text))

def debug_error():
    for line in traceback.format_exc().splitlines()[0:10]:
        debug_problem(line)

def output_running(workitem):
    print(':RUNNING:{}'.format(workitem['name']))

def output_success(workitem):
    print(':SUCCESS:')

def output_failure(workitem):
    print(':FAILURE:')

try:
    import jycessing.Runner, jycessing.RunnableSketch, jycessing.StreamPrinter
except:
    debug_problem("I can't import the Java code I need to run sketches.")
    debug_problem("Note: don't run this file directly; just use generator.py.")
    sys.exit(1) 

class ExampleImageGenSketch(jycessing.RunnableSketch):
    def __init__(self, workitem):
        self.scriptfile = workitem['scriptfile']
        self.imagefile= workitem['imagefile']
        self.srcdir = os.path.dirname(self.scriptfile)
        self.code = workitem['code']

    def gen_image(self):
        out_printer = jycessing.StreamPrinter(java.lang.System.out)
        err_printer = jycessing.StreamPrinter(java.lang.System.err)
        jycessing.Runner.runSketchBlocking(self, out_printer, err_printer)

    # Functions to satisfy interface:
    def getMainFile(self):
        return java.io.File(self.scriptfile)

    def getMainCode(self):
        return self.code

    def getHomeDirectory(self):
        return java.io.File(self.srcdir)

    def getPathEntries(self):
        entries = java.util.ArrayList()
        entries.add(java.io.File(self.srcdir))
        return entries

    def getPAppletArguments(self):
        return jarray.array([self.scriptfile], java.lang.String)
    
    def getLibraryDirectories(self):
        dirs = java.util.ArrayList()
        return dirs # TODO what else should we have here?

    def getLibraryPolicy(self):
        return jycessing.Runner.LibraryPolicy.PROMISCUOUS

    def shouldRun(self):
        return 1

def gen(workitems):
    for workitem in workitems:
        output_running(workitem)
        try:
            with open(workitem['scriptfile']) as f:
                workitem['code'] = f.read()
            sketch = ExampleImageGenSketch(workitem)
            sketch.gen_image()
            output_success(workitem)
        except jycessing.PythonSketchError, e:
            if "NullPointerException" in e.getMessage():
                debug_problem("NullPointerException - {} is probably dynamic-mode; fix that, please.".format(workitem['name']))
            else:
                debug_error()
            output_failure(workitem)
        except:
            debug_error()
            output_failure(workitem)

if __name__ == '__main__':
    debug('Image process started.')
    parser = argparse.ArgumentParser(description='Build a set of images.') 
    parser.add_argument('--todo', nargs='+', type=str)
    args = parser.parse_args()
    try:
        workitems = []
        for obj in args.todo:
            name, scriptfile, imagefile = obj.split(':')
            workitems.append({'name':name, 'scriptfile':scriptfile, 'imagefile':imagefile})
        gen(workitems)
    except:
        debug_error()
        sys.exit(1)
