from __future__ import print_function
import os, re
import lxml.etree

name_file_dict = {}
filenames = filter(lambda f: f.endswith('.xml'), os.listdir('Reference/api_en'))

for filename in filenames:
    tree = lxml.etree.parse('Reference/api_en/' + filename)
    name = tree.find('name').text
    name_file_dict[name] = filename[:-4]

whitespace = re.compile(r'^\s*$')
related_regex = re.compile(r'<related>([^<]*)</related>')

problems = set()

for filename in filenames:
    print('Handling', filename)
    with open('Reference/api_en/' + filename, 'r') as file:
        content = file.read()
    related_str = related_regex.search(content).group(1)
    relateds = map(lambda z: z.strip(), filter(lambda s: not whitespace.match(s), related_str.split('\n')))
    repstr = '<related>\n'
    for related in relateds:
        print('  in {}, {}'.format(filename, related))
        try:
            target = name_file_dict[related]
        except:
            print('No match for {}'.format(related))
            problems.add(filename)
            target = '?????'
        repstr += '<ref target="{}">{}</ref>\n'.format(target, related)
    repstr += '</related>'
    print(repstr)
    finalstr = related_regex.sub(repstr, content)
    with open('Reference/api_en/' + filename, 'w') as file:
        file.write(finalstr)
    print('Wrote result.')

print('Problem children:')
for problem in problems:
    print(problem, end=' ')
print()
