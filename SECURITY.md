# Security

playcal runs on your machine and talks to a local Unity Editor through Unity's own CLI. It opens no network ports of its own; `playcal mcp` speaks over stdio.

If you find a security problem (for example a crafted event file, paste blob or Unity response that makes playcal run code or write outside the project), please don't open a public issue. Use GitHub's private vulnerability reporting on this repository, or email rizgarozan7@gmail.com. You'll get an answer within a week.

Only the latest release gets fixes while the project is pre-1.0.
