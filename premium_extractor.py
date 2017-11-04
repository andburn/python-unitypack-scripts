#!/usr/bin/env python
import json
import os
import sys
from argparse import ArgumentParser
from PIL import Image, ImageOps
from unitypack.environment import UnityEnvironment

from utils import vec_from_dict, write_to_file

"""Based on HearthSim/HearthstoneJSON generate_card_textures.py"""

guid_to_path = {}


def handle_rad_node(path, guids, names, tree, node):
	if len(node["folderName"]) > 0:
		if len(path) > 0:
			path = path + "/" + node["folderName"]
		else:
			path = node["folderName"]

	for leaf in node["leaves"]:
		guid = guids[leaf["guidIndex"]]
		name = names[leaf["fileNameIndex"]]
		guid_to_path[guid] = path + "/" + name

	for child in node["children"]:
		handle_rad_node(path, guids, names, tree, tree[child])


def handle_rad(rad):
	#print("Handling RAD")
	guids = rad["m_guids"]
	names = rad["m_filenames"]
	tree = rad["m_tree"]
	handle_rad_node("", guids, names, tree, tree[0])


def handle_asset(asset, textures, cards, filter_ids):
	for obj in asset.objects.values():
		if obj.type == "AssetBundle":
			d = obj.read()
			for path, obj in d["m_Container"]:
				path = path.lower()
				asset = obj["asset"]
				if path == "assets/rad/rad_base.asset":
					handle_rad(asset.resolve())
				if not path.startswith("final/"):
					path = "final/" + path
				if not path.startswith("final/assets"):
					continue
				textures[path] = asset

		elif obj.type == "GameObject":
			d = obj.read()

			if d.name == "rad_base":
				handle_rad(d)
				continue

			cardid = d.name
			if filter_ids and cardid not in filter_ids:
				continue
			if cardid in ("CardDefTemplate", "HiddenCard"):
				# not a real card
				cards[cardid] = {"path": "", "tile": ""}
				continue
			if len(d.component) < 2:
				# Not a CardDef
				continue
			script = d.component[1]
			if isinstance(script, dict):  # Unity 5.6+
				carddef = script["component"].resolve()
			else:  # Unity <= 5.4
				carddef = script[1].resolve()

			if not isinstance(carddef, dict) or "m_PortraitTexturePath" not in carddef:
				# Not a CardDef
				continue

			path = carddef["m_PortraitTexturePath"]
			if not path:
				# Sometimes there's multiple per cardid, we remove the ones without art
				continue

			if ":" in path:
				guid = path.split(":")[1]
				if guid in guid_to_path:
					path = guid_to_path[guid]
				else:
					print("WARN: Could not find %s in guid_to_path (path=%s)" % (guid, path))

			path = "final/" + path

			# premium path
			prem_path = carddef["m_PremiumPortraitMaterialPath"]
			if not prem_path:
				print("premium path not found")
				continue

			if ":" in prem_path:
				guid = prem_path.split(":")[1]
				if guid in guid_to_path:
					prem_path = guid_to_path[guid]
				else:
					print("WARN: Could not find %s in guid_to_path (path=%s)" % (guid, prem_path))

			prem_path = "final/" + prem_path

			# uber animation path
			prem_uber_path = carddef["m_PremiumUberShaderAnimationPath"]
			if not prem_uber_path:
				print("premium uber path not found")
			else:
				if ":" in prem_uber_path:
					guid = prem_uber_path.split(":")[1]
					if guid in guid_to_path:
						prem_uber_path = guid_to_path[guid]
					else:
						print("WARN: Could not find %s in guid_to_path (path=%s)" % (guid, prem_path))

				prem_uber_path = "final/" + prem_uber_path

			# premium portrait
			prem_port_path = carddef["m_PremiumPortraitTexturePath"]
			if not prem_port_path:
				print("premium port path not found")
			else:
				if ":" in prem_port_path:
					guid = prem_port_path.split(":")[1]
					if guid in guid_to_path:
						prem_port_path = guid_to_path[guid]
					else:
						print("WARN: Could not find %s in guid_to_path (path=%s)" % (guid, prem_path))

				prem_port_path = "final/" + prem_port_path

			tile = carddef.get("m_DeckCardBarPortrait")
			if tile:
				tile = tile.resolve()

			cards[cardid] = {
				"path": path.lower(),
				"prem_path": prem_path.lower(),
				"prem_uber": prem_uber_path.lower(),
				"prem_port": prem_port_path.lower(),
				#"tile": tile.saved_properties if tile else {},
			}



def extract_info(files, filter_ids):
	cards = {}
	textures = {}
	env = UnityEnvironment()

	for file in files:
		#print("Reading %r" % (file))
		f = open(file, "rb")
		env.load(f)

	for bundle in env.bundles.values():
		for asset in bundle.assets:
			#print("Parsing %r" % (asset.name))
			handle_asset(asset, textures, cards, filter_ids)

	return cards, textures


def get_dir(basedir, dirname):
	ret = os.path.join(basedir, dirname)
	if not os.path.exists(ret):
		os.makedirs(ret)
	return ret


def get_filename(basedir, dirname, name, ext=".png"):
	dirname = get_dir(basedir, dirname)
	filename = name + ext
	path = os.path.join(dirname, filename)
	return path, os.path.exists(path)


def do_texture(path, id, textures, values, thumb_sizes, args):
	print("Parsing %r (%r)" % (id, path))
	if not path:
		print("%r does not have a texture" % (id))
		return

	if path not in textures:
		print("Path %r not found for %r" % (path, id))
		return

	pptr = textures[path]
	texture = pptr.resolve()
	flipped = None

	filename, exists = get_filename(args.outdir, args.orig_dir, id, ext=".png")
	if not (args.skip_existing and exists):
		print("-> %r" % (filename))
		flipped = ImageOps.flip(texture.image).convert("RGB")
		flipped.save(filename)

	for format in args.formats:
		ext = "." + format

		if not args.skip_tiles:
			filename, exists = get_filename(args.outdir, args.tiles_dir, id, ext=ext)
			if not (args.skip_existing and exists):
				tile_texture = generate_tile_image(texture.image, values["tile"])
				print("-> %r" % (filename))
				tile_texture.save(filename)

		if ext == ".png":
			# skip png generation for thumbnails
			continue

		if args.skip_thumbnails:
			# --skip-thumbnails was specified
			continue

		for sz in thumb_sizes:
			thumb_dir = "%ix" % (sz)
			filename, exists = get_filename(args.outdir, thumb_dir, id, ext=ext)
			if not (args.skip_existing and exists):
				if not flipped:
					flipped = ImageOps.flip(texture.image).convert("RGB")
				thumb_texture = flipped.resize((sz, sz))
				print("-> %r" % (filename))
				thumb_texture.save(filename)


class VectorEncoder(json.JSONEncoder):
	def default(self, obj):
		if hasattr(obj, "to_json"):
			return obj.to_json()
		else:
			info(f"{obj} does not implement to_json()")
			return json.JSONEncoder.default(self, obj)


def main():
	p = ArgumentParser()
	p.add_argument("--only", type=str, nargs="?", help="Extract specific IDs")
	p.add_argument("files", nargs="+")
	p.add_argument("outdir")
	args = p.parse_args(sys.argv[1:])

	filter_ids = args.only.split(",") if args.only else []

	cards, textures = extract_info(args.files, filter_ids)
	paths = [card["path"] for card in cards.values()]
	print("Found %i cards, %i textures including %i unique in use." % (
		len(cards), len(textures), len(set(paths))
	))

	for id, values in sorted(cards.items()):
		if filter_ids and id not in filter_ids:
			continue

		# test for premium properties
		# has_prem = [id]
		# try:
		# 	if values["prem_uber"]:
		# 		has_prem.append("uber_anim")
		# 		if values["path"]:
		# 			has_prem.append("port")
		# 		if values["prem_path"]:
		# 			has_prem.append("prem_path")
		# 		if values["prem_port"]:
		# 			has_prem.append("prem_port")
		# 		print(" : ".join(has_prem))
		# 	continue
		# except:
		# 	continue
		# end test

		print(values)

		path = values["path"]
		pptr = textures[path]
		portrait = pptr.resolve()
		fn, fexists = get_filename(args.outdir, id, "portrait", ext=".png")
		portrait.image.save(fn)

		# get material
		prem_path = values["prem_path"]
		pptr = textures[prem_path]
		prem_mat = pptr.resolve()

		prem_obj = {}
		prem_obj["name"] = prem_mat.name
		prem_obj["shader"] = prem_mat.shader.resolve()._obj["m_ParsedForm"]["m_Name"]
		prem_obj["keywords"] = prem_mat.shader_keywords

		for tname, v in prem_mat.saved_properties["m_TexEnvs"].items():
			tptr = v["m_Texture"]
			if not tptr:
				prem_obj[tname] = None
				continue
			texture_obj = tptr.resolve()
			filename, exists = get_filename(args.outdir, id, texture_obj.name, ext=".png")
			texture_obj.image.save(filename)
			prem_obj[tname] = {}
			prem_obj[tname]["texture"] = texture_obj.name
			prem_obj[tname]["scale"] = vec_from_dict(v["m_Scale"])
			prem_obj[tname]["offset"] = vec_from_dict(v["m_Offset"])

		for fname, v in prem_mat.saved_properties["m_Floats"].items():
			prem_obj[fname] = float(v)

		for cname, v in prem_mat.saved_properties["m_Colors"].items():
			prem_obj[cname] = vec_from_dict(v)

		filename, exists = get_filename(args.outdir, id, id, ext=".json")
		write_to_file(filename, json.dumps(prem_obj, cls=VectorEncoder, indent=4))

		# premium port path
		prem_port_path = values["prem_port"]
		if prem_port_path:
			pptr = textures[prem_port_path]
			portrait = pptr.resolve()
			fn, fexists = get_filename(args.outdir, id, "portrait_prem", ext=".png")
			portrait.image.save(fn)

		# premium uber shader animation
		puber_path = values["prem_uber"]
		if puber_path:
			pptr = textures[puber_path]
			data = pptr.resolve()
			filename, exists = get_filename(args.outdir, id, id + "_animation", ext=".json")
			write_to_file(filename, data.bytes)


		# NOTE
		# since Ungoro, UberShaderAnimations exist for cards
		#   alternative/extension to shader material?
		# separate premium portrait now also exists for some cards
		#   does seem to be included in material object though (as _Main_Tex)
		# known premium props:
		#   m_PremiumPortraitMaterialPath
		#   m_PremiumUberShaderAnimationPath
		#   m_PremiumPortraitTexturePath


if __name__ == "__main__":
	main()
