
#!/usr/bin/env python3
import os, json, logging, sys
from pathlib import Path

ROOT_FOLDER = r"/home/kali/Documents/Scripts/ABC/Files"
OUTPUT_FILE="filetree_output.txt"
ERROR_FILE="error_log.txt"
CHECKPOINT="crawl_checkpoint.json"
SAVE_EVERY=100

logging.basicConfig(filename=ERROR_FILE, level=logging.ERROR)

def human(n):
    u=["B","KB","MB","GB","TB"]
    f=float(n)
    i=0
    while f>=1024 and i<len(u)-1:
        f/=1024;i+=1
    return f"{f:.2f} {u[i]}" if i else f"{int(f)} B"

def rel_parts(path):
    return list(Path(path).relative_to(ROOT_FOLDER).parts)

def win(parts,folder=False):
    p="\\"+"\\".join(parts)
    return p+"\\" if folder else p

visited=set()
stack=[]
count=0

def save():
    tmp=CHECKPOINT+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump({"visited":list(visited),"stack":stack},f,ensure_ascii=False,indent=2)
    os.replace(tmp,CHECKPOINT)

if os.path.exists(CHECKPOINT):
    with open(CHECKPOINT,encoding="utf-8") as f:
        d=json.load(f)
    visited=set(d["visited"]); stack=d["stack"]
else:
    stack=[[ROOT_FOLDER,[]]]
    if os.path.exists(OUTPUT_FILE): os.remove(OUTPUT_FILE)

out=open(OUTPUT_FILE,"a",encoding="utf-8")

try:
    while stack:
        current,parts=stack.pop()
        if current in visited: continue
        visited.add(current)
        try:
            entries=list(os.scandir(current))
        except Exception as e:
            logging.error("%s | %s",current,e)
            continue
        folders=[]
        for e in entries:
            if e.is_symlink():
                continue
            rel=rel_parts(e.path)
            if e.is_dir(follow_symlinks=False):
                line=f"[FOLDER] {win(rel,True)}"
                print("[SAVED]",line)
                out.write(line+"\n")
                folders.append([e.path,rel])
            elif e.is_file(follow_symlinks=False):
                try:s=human(e.stat().st_size)
                except:s="N/A"
                line=f"[FILE]   {win(rel)} | {s}"
                print("[SAVED]",line)
                out.write(line+"\n")
        for f in reversed(folders):
            stack.append(f)
        count+=1
        if count%SAVE_EVERY==0:
            save()
finally:
    save()
    out.close()
    print("Done.")
