"""Canonical avatar item identity shared by runtime and offline builders.

This module intentionally imports no client parsers, database or filesystem
helpers. Callers must verify worn slot semantics before supplying a recipe.
"""
import hashlib
import json


AVATAR_SLOTS=frozenset('['+part+' avatar]' for part in
    ('hat','hair','face','breast','coat','skin','waist','pants','shoes'))


class OutfitRecipeError(ValueError):
    pass


def canonical_outfit_recipe(job,items):
    """Hash explicit item identities; exclude account/character identifiers."""
    if type(job) is not int or not 0<=job<=255 or not isinstance(items,(list,tuple)) or len(items)>len(AVATAR_SLOTS):
        raise OutfitRecipeError('Invalid outfit job or item count')
    result=[];seen=set()
    for item in items:
        if not isinstance(item,dict) or set(item)!={'slot','id'}:raise OutfitRecipeError('Invalid outfit item fields')
        slot,identity=item['slot'],item['id']
        if not isinstance(slot,str) or slot not in AVATAR_SLOTS or slot in seen:raise OutfitRecipeError('Invalid or duplicate outfit slot')
        if type(identity) is not int or not 1<=identity<=0x7fffffff:raise OutfitRecipeError('Invalid outfit item ID')
        seen.add(slot);result.append({'slot':slot,'id':identity})
    recipe={'job':job,'items':sorted(result,key=lambda item:item['slot'])}
    encoded=json.dumps(recipe,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
    return recipe,hashlib.sha256(encoded).hexdigest()
