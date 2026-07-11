# Issue tracker: GitHub

Issues and PRDs for this repository live in GitHub Issues at `selfAnnihilator/pixel-pet`. Use the `gh` CLI from the repository root so it infers the repository from `origin`.

## Conventions

- Create: `gh issue create --title "..." --body-file <file>`.
- Read: `gh issue view <number> --comments`.
- List: `gh issue list --state open --json number,title,body,labels,comments`.
- Comment: `gh issue comment <number> --body "..."`.
- Label: `gh issue edit <number> --add-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

When an engineering skill says to publish to the issue tracker, create a GitHub issue.
