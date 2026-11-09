# Contributing to geofileops

(Contribution guidelines largely copied from
[geopandas](https://github.com/geopandas/geopandas/blob/main/CONTRIBUTING.md))

## Overview

Contributions to geofileops are very welcome. They are likely to be accepted more quickly
if they follow these guidelines.

At this stage of geofileops development, the priorities are to define a simple, usable,
and stable API and to have clean, maintainable, readable code. Performance matters, but
not at the expense of those goals.

In general, geofileops follows the conventions of the geopandas project where applicable.

In particular, when submitting a pull request:

- All existing tests should pass. Please make sure that the test suite passes, both
  locally and on [GitHub Actions](https://github.com/geofileops/geofileops/actions).
  Status on GHA will be visible on a pull request.
- New functionality should include tests. Please write reasonable tests for your code
  and make sure that they pass on your pull request.
- Classes, methods, functions, etc. should have docstrings. The first line of a
  docstring should be a standalone summary. Parameters and return values should be
  documented explicitly.
- Follow PEP 8 when possible. We use [ruff](https://docs.astral.sh/ruff/) to ensure a
  consistent code format throughout the project. For more details see the section _Style
  Guide_ below.
- Unless your PR implements minor changes or internal work only, make sure it contains a
  note describing the changes in the `CHANGELOG.md` file.

### Steps for Contributing

These are the basic steps to contribute to geofileops:

1. Fork the geofileops git repository 
2. Create a development environment 
3. Make changes to code and add tests 
4. Update the documentation 
5. Submit a Pull Request

Each of these steps is detailed below.

## 1) Forking the geofileops repository using Git

To the new user, working with Git is one of the more daunting aspects of contributing to
geofileops. It can very quickly become overwhelming, but sticking to the guidelines below
will help keep the process straightforward and mostly trouble free.

The code is hosted on [GitHub](https://github.com/geofileops/geofileops). To contribute
you will need to sign up for a [free GitHub account](https://github.com/signup/free). We
use [Git](http://git-scm.com/) for version control to allow many people to work together
on the project.

Using [GitHub Desktop](https://github.com/apps/desktop) simplifies the process a lot and
avoids having to use the command line commands below in most situations.

Some great resources for learning Git:

- Software Carpentry\'s [Git Tutorial](http://swcarpentry.github.io/git-novice/)
- [Atlassian](https://www.atlassian.com/git/tutorials/what-is-version-control)
- the [GitHub help pages](http://help.github.com/).
- Matthew Brett\'s [Pydagogue](https://matthew-brett.github.io/pydagogue/).

### Getting started with Git

[GitHub has instructions](https://github.com/git-guides/install-git) for installing
git, setting up your SSH key, and configuring git. All these steps need to be completed
before you can work seamlessly between your local repository and GitHub.

### Forking

You will need your own fork to work on the code. Go to the [geofileops project
page](https://github.com/geofileops/geofileops) and hit the `Fork` button. You will want
to clone your fork to your machine:

    git clone git@github.com:your-user-name/geofileops.git geofileops-yourname 
    cd geofileops-yourname 
    git remote add upstream git://github.com/geofileops/geofileops.git

This creates the directory `geofileops-yourname` and connects your repository to the
upstream (main project) geofileops repository.

The testing suite will run automatically on GitHub Actions once your pull request is
submitted. The test suite will also automatically run on your branch so you can check it
prior to submitting the pull request.

### Creating a branch

You want your main branch to reflect only production-ready code, so create a feature
branch for making your changes. For example:

    git branch shiny-new-feature 
    git checkout shiny-new-feature

The above can be simplified to:

    git checkout -b shiny-new-feature

This changes your working directory to the shiny-new-feature branch. Keep any changes in
this branch specific to one bug or feature so it is clear what the branch brings to
geofileops. You can have many shiny-new-features and switch in between them using the git
checkout command.

To update this branch, you need to retrieve the changes from the main branch:

    git fetch upstream 
    git rebase upstream/main

This will replay your commits on top of the latest geofileops git main. If this leads to
merge conflicts, you must resolve these before submitting your pull request. If you have
uncommitted changes, you will need to `stash` them prior to updating. This will
effectively store your changes and they can be reapplied after updating.

## 2) Creating a development environment

A development environment is a virtual space where you can keep an independent
installation of geofileops. This makes it easy to keep both a stable version of python in
one place you use for work, and a development version (which you may break while playing
with code) in another.

An easy way to create a geofileops development environment is as follows:

- Install [miniforge](https://github.com/conda-forge/miniforge#miniforge)
- Make sure that you have cloned the repository
- `cd` to the `geofileops` source directory

### Using the provided environment

geofileops provides an environment which includes the required dependencies for
development. The environment file is located in the top level of the repo and is named
`environment-dev.yml`. You can create this environment by navigating to the
`geofileops` source directory and running:

    conda env create -f environment-dev.yml

This will create a new conda environment named `geofileops-dev`.

### Working with the environment

To work in this environment, you need to `activate` it. The instructions below should
work for both Windows, Mac and Linux:

    conda activate geofileops-dev

Once your environment is activated, you will see a confirmation message to indicate you
are in the new development environment.

To view your environments:

    conda info -e

To return to you home root environment:

    conda deactivate

See the full conda docs [here](http://conda.pydata.org/docs).

## 3) Making changes and writing tests

geofileops is serious about testing and strongly encourages contributors to embrace
[test-driven development (TDD)](http://en.wikipedia.org/wiki/Test-driven_development).
This development process "relies on the repetition of a very short development cycle:
first the developer writes an (initially failing) automated test case that defines a
desired improvement or new function, then produces the minimum amount of code to pass
that test." So, before actually writing any code, you should write your tests. Often
the test can be taken from the original GitHub issue. However, it is always worth
considering additional use cases and writing corresponding tests.

geofileops uses the [pytest testing system](http://doc.pytest.org/en/latest/).

### Writing tests

All tests should go into the `tests` sub-directory. This folder contains many current
examples of tests, and we suggest looking to these for inspiration.

### Running the test suite

The tests can then be run directly inside your Git clone (without having to install
geofileops) by typing:

    pytest

## 4) Updating the Documentation

geofileops documentation resides in the `doc` folder. Changes to the docs are made by
modifying the appropriate file in the `source` folder within `doc`. geofileops docs use
mixture of reStructuredText syntax for `rst` files, [which is explained
here](http://www.sphinx-doc.org/en/stable/rest.html#rst-primer) and MyST syntax for `md`
files [explained here](https://myst-parser.readthedocs.io/en/latest/index.html).

We highly encourage you to follow the [Google developer documentation style
guide](https://developers.google.com/style/highlights) when updating or creating new
documentation.

The documentation will be built when you create a pull request.

## 5) Submitting a Pull Request

Once you've made changes and pushed them to your forked repository, you then submit a
pull request to have them integrated into the geofileops code base.

You can find a pull request (or PR) tutorial in the [GitHub's Help
Docs](https://help.github.com/articles/using-pull-requests/).

## Style Guide & Linting

geofileops follows the [PEP8](http://www.python.org/dev/peps/pep-0008/) standard and uses
[ruff](https://docs.astral.sh/ruff/) to ensure a consistent code format throughout the
project.

Continuous Integration (GitHub Actions) will run those tools and report any stylistic
errors in your code. Therefore, it is helpful before submitting code to run the check
yourself:

    ruff format geofileops 
    ruff check geofileops 
    git diff upstream/main -u -- "*.py" | ruff check .

to auto-format your code. Additionally, many editors have plugins that will apply `ruff`
as you edit files.

Optionally (but recommended), you can setup [pre-commit hooks](https://pre-commit.com/)
to automatically run `ruff` when you make a git commit. If you did not use the provided
development environment in `environment-dev.yml`, you must first install `pre-commit`:

    $ python -m pip install pre-commit

From the root of the geofileops repository, you should then install the `pre-commit`
included in geofileops:

    $ pre-commit install

Then `ruff` will be run automatically each time you commit changes. You can skip these
checks with `git commit --no-verify`.

## Commit message conventions

Commit your changes to your local repository with an explanatory message. geofileops uses
the pandas convention for commit message prefixes and layout. Here are some common
prefixes along with general guidelines for when to use them:

- ENH: Enhancement, new functionality
- BUG: Bug fix
- DOC: Additions/updates to documentation
- TST: Additions/updates to tests
- BLD: Updates to the build process/scripts
- PERF: Performance improvement
- TYP: Type annotations
- CLN: Code cleanup

The following defines how a commit message should be structured. Please refer to the
relevant GitHub issues in your commit message using GH1234 or #1234. Either style is
fine, but the former is generally preferred:

- a subject line with < 80 characters.
- One blank line.
- Optionally, a commit message body.

Now you can commit your changes in your local repository:

    git commit -m

## AI Assisted Contributions

We recognise that AI coding assistants are now a regular part of many developers\'
workflows. However, AI-generated PRs can sometimes lead to undesirable additional
maintainer burden. PRs that appear to be fully generated by AI with little to no
engagement from the author may be closed without further review.

Remember that maintainers volunteer to support geofileops, and low quality AI generated
Pull Requests are not an effective use of that precious time - a contribution should be
worth more to the project than the time it takes to review it. Ultimately, the person
submitting an issue or PR is responsible for its content, regardless of whether AI tools
were used in its creation and they must ensure the contribution meets the geofileops
guidelines.

We are not opposed to the use of AI tools in writing PRs, but require the following:

- Only submit a PR if you are able to debug and own the changes yourself - review all
  generated code to understand every detail
- Match the style and conventions used in the rest of the codebase, including PR titles
  and descriptions
- Be upfront about AI usage and summarise what was AI-generated
- If there are parts you don\'t fully understand, leave comments on your own PR
  explaining what steps you took to verify correctness
- Watch for AI\'s tendency to generate overly verbose comments, unnecessary test cases,
  and incorrect fixes
- Break down large PRs into smaller ones to make review easier
- AI agents should never tag or ping maintainers
- AI generated PRs will not be accepted unless they resolve an existing issue where
  there is consensus on the solution to implement. If no issue exists, open a new issue
  and engage to gather consensus.

When interacting with developers (forums, discussions, issues, pull requests, etc.) do
not use AI to speak for you, except for translation or grammar editing. If the
developers want to chat with a chatbot, they can do so themselves. Human-to-human
communication is essential for an open source community to thrive.

This policy is adapted in part from the Apache Arrow AI-generated code Contribution
guidelines.
