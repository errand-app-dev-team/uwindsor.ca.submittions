# uwindsor.ca Submissions

This repository collects the project submissions from every group. Each group
submits its work on **its own branch**. Nothing should be committed directly to
`main`.

## The one rule

**Create a branch named after your group and push all of your work to that
branch.**

Git branch names cannot contain spaces, so write the group name with a hyphen:

| Your group | Your branch name |
|------------|------------------|
| Group 1    | `group-1`        |
| Group 2    | `group-2`        |
| Group 6    | `group-6`        |
| Group 12   | `group-12`       |

Use lowercase `group`, a hyphen, and your group number. Do not add anything
else to the name.

## Step-by-step

The example below is for **Group 6**. Replace `6` with your own group number.

### 1. Clone the repository

```bash
git clone https://github.com/errand-app-dev-team/uwindsor.ca.submittions.git
cd uwindsor.ca.submittions
```

### 2. Create your group's branch and switch to it

```bash
git checkout -b group-6
```

Confirm you are on the right branch before you continue:

```bash
git branch --show-current
# should print: group-6
```

### 3. Add your project files

Copy your project into the repository folder. Then stage and commit the files:

```bash
git add .
git commit -m "Group 6: initial submission"
```

### 4. Push your branch to GitHub

The first push needs the `-u` flag so Git links your local branch to the remote
one:

```bash
git push -u origin group-6
```

After that, any further changes can be pushed with just:

```bash
git push
```

### 5. Check your work on GitHub

Open the repository on GitHub, use the branch dropdown (it says `main` by
default), and select your branch. Your files should be there.

## Updating your submission

You can push to your branch as many times as you like before the deadline.
Make sure you are on your group's branch, then:

```bash
git add .
git commit -m "Describe what you changed"
git push
```

## If your group's branch already exists

If a teammate has already created and pushed the branch, do **not** create it
again. Check it out instead:

```bash
git fetch origin
git checkout group-6
```

Then pull before you start working so you have your teammates' latest changes:

```bash
git pull
```

## Do not

- Do **not** commit or push to `main`.
- Do **not** push to another group's branch.
- Do **not** use a branch name other than `group-<your number>`.
- Do **not** commit large binaries, `node_modules/`, virtual environments, build
  output, or secrets such as API keys. Add a `.gitignore` to your branch for
  these.

## Checklist before the deadline

- [ ] My branch is named `group-<number>` with my group's number.
- [ ] All of my group's code is committed and pushed to that branch.
- [ ] I can see the files on GitHub when I select my branch.
- [ ] Nothing from my group was pushed to `main`.

## Need help?

If you accidentally pushed to the wrong branch, or you are not sure whether your
submission went through, contact the course staff **before** the deadline. Do
not try to force-push or delete branches to fix it yourself.
