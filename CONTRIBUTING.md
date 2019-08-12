## Contributing

Thank you for your interest in contributing to the Python Mode for Processing
reference documentation and website. We welcome contributions!

To contribute new documentation or fixes to the
existing documentation, create a fork of the
[processing-py-site](https://github.com/jdf/processing-py-site) repository
on GitHub. With `git`, create a new branch in your fork and make your changes,
ensuring that `python generator.py build --all --images` completes without
errors. When you're done, push your branch to your fork of the project on
Github, and then issue a Pull Request against the main repository. [Here's a
good overview of the pull request
process](https://yangsu.github.io/pull-request-tutorial/) on GitHub. (If you're
totally unfamiliar with Git or GitHub, [try this
tutorial](https://try.github.io/).

Pull requests will be automatically tested Travis-CI, and will receive a pass
or fail mark. If the build fails, please review the log for why. Common reasons
may include metadata categort checks by generator.py, or generate_images.py not
generating an image. For troubleshooting, see [README.md](README.md).

All contributions are distributed under the current license, see:
[LICENSE](LICENSE).

This license is for the website documentation of Python Mode for Processing.
The Python Mode for Processing software is licensed seperately, currently under
Apache 2.0.
