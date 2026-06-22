# -*- coding: utf-8 -*-
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("postcode-validator")

@mcp.tool()
async def validate_postcode(postcode: str) -> dict:
    """Validate a UK postcode using the postcodes.io API.

    Args:
        postcode: The UK postcode to validate (e.g., 'SW1A 1AA').

    Returns:
        A dict containing 'valid' (bool) and information or error.
    """
    clean_postcode = postcode.strip().replace(" ", "")
    url = f"https://api.postcodes.io/postcodes/{clean_postcode}/validate"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                result = response.json()
                is_valid = result.get("result", False)
                return {
                    "valid": is_valid,
                    "postcode": postcode,
                    "clean_postcode": clean_postcode
                }
            return {
                "valid": False,
                "postcode": postcode,
                "error": f"API returned status code {response.status_code}"
            }
    except Exception as e:
        return {
            "valid": False,
            "postcode": postcode,
            "error": str(e)
        }

if __name__ == "__main__":
    mcp.run()
