# Homework 2: Policy Gradients

## Setup

For general setup and Modal instructions, see Homework 1's README.

## Examples

Here are some example commands. Run them in the `hw2` directory.

* To run on a local machine:
  ```bash
  uv run src/scripts/run.py --env_name CartPole-v0 -n 100 -b 1000 --exp_name cartpole
  ```


* To run on Modal:
  ```bash
  uv run modal run src/scripts/modal_run.py --env_name CartPole-v0 -n 100 -b 1000 --exp_name cartpole
  ```
  * Note that Modal is likely not necessary for this assignment.
In testing, training was much faster on a local laptop CPU than on Modal.
However, you may still use Modal if you wish.
  * You may request a different GPU type, CPU count, and memory size by changing variables in `src/scripts/modal_run.py`
  * Use `modal run --detach` to keep your job running in the background.

## Troubleshooting

* If you see an error about `swig` when installing `box2d-py`, you may need to install `swig` and `cmake` on your machine.
If you are using a Mac and have Homebrew installed, you can run `brew install swig cmake`.
On Modal, it should already be installed.

## Submission

From within the `hw2/` directory, run the following command.

```bash
uv run ../submit.py
```

This will generate a `submit.zip` archive that you can upload to Gradescope.
