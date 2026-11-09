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


def canonical_appearance_recipe(job,grow_type,items,weapon_id=0,aura_id=0):
    """v2 visual identity; inventory instance links never enter the public key.

    Dye IDs are retained even when rendering them is unsupported. They must
    never collide with the undyed appearance or be interpreted as RGB values.
    """
    if type(grow_type) is not int or not -128<=grow_type<=255:
        raise OutfitRecipeError('Invalid appearance growth identity')
    if type(weapon_id) is not int or not 0<=weapon_id<=0x7fffffff:
        raise OutfitRecipeError('Invalid appearance weapon identity')
    if type(aura_id) is not int or not 0<=aura_id<=0x7fffffff:
        raise OutfitRecipeError('Invalid appearance aura identity')
    plain=[];colors={}
    if not isinstance(items,(list,tuple)):raise OutfitRecipeError('Invalid appearance items')
    for item in items:
        if not isinstance(item,dict) or set(item)-{'slot','id','color1','color2'}:
            raise OutfitRecipeError('Invalid appearance fields')
        dye=(item.get('color1',0),item.get('color2',0))
        if any(type(c) is not int or not -32768<=c<=32767 for c in dye):
            raise OutfitRecipeError('Invalid appearance dye identifier')
        plain.append({'slot':item.get('slot'),'id':item.get('id')});colors[item.get('slot')]=dye
    base,_=canonical_outfit_recipe(job,plain)
    recipe={'version':2,'job':job,'grow_type':grow_type&127,'weapon_id':weapon_id,'aura_id':aura_id,
            'items':[{**item,'color1':colors[item['slot']][0],'color2':colors[item['slot']][1]} for item in base['items']]}
    encoded=json.dumps(recipe,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
    return recipe,hashlib.sha256(encoded).hexdigest()
