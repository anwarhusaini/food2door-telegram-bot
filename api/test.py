#!/usr/bin/env python3
"""
Vercel Python Serverless Function - Test
"""
import json

def handler(request):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"message": "Hello from Vercel!", "path": request.path})
    }
