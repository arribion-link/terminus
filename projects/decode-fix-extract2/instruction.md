navigate a hash-addressed dependency chain to find and execute a hidden command.

a data directory at /app/data/ contains several files. among them is a file named manifest.txt, which contains the starting hash for a dependency chain.

each file in the chain is named by the sha256 hex digest of its own content. the content of each chain file contains a line of informational text, followed by either a "NEXT:" link (with the sha256 hash of the next file) or an "EXEC:" command (the final file in the chain).

there are also decoy files in the directory that are not part of the chain. you must follow exactly the chain starting from the hash in manifest.txt.

your task:
1. read /app/data/manifest.txt to get the starting hash
2. find the file named by that hash in /app/data/
3. read its content. if it contains "NEXT: <hash>", find and read the file with that hash. repeat.
4. when you find a file containing "EXEC: <command>", execute that command in a shell
5. capture the full stdout output of that command and write it to /app/result.txt

the result file /app/result.txt must contain exactly the output of the final exec command, with no extra text before or after.

you may use any combination of python, bash, or standard unix tools to traverse the chain.
