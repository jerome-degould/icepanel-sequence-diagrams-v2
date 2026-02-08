import os
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from os import environ

import requests

headers = {"Authorization": f"ApiKey {environ['API_KEY']}"}

landscape_id = environ['LANDSCAPE_ID']
version_id = environ['LANDSCAPE_VERSION']


class MermaidExportType(str, Enum):
    svg = "svg"
    png = "png"


class SequenceParticipant:
    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __repr__(self):
        return f"{self.id} - {self.name}"


class SequenceInteraction:
    def __init__(self, id, type, description, source_id, target_id):
        self.id = id
        self.type = type
        self.description = description
        self.source_id = source_id
        self.target_id = target_id

    def __str__(self):
        return f"{self.id} - {self.type} - {self.description} - {self.source_id} - {self.target_id}"


class MermaidSequence:

    def __init__(self, name):
        self.name = name
        self.participants = {}
        self.sequence_steps = []

    def add_participant(self, participant: SequenceParticipant):
        if participant.id not in self.participants:
            self.participants[participant.id] = participant

    def add_sequence_step(self, sequence_step: SequenceInteraction):
        self.sequence_steps.append(sequence_step)

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def generate(self):
        graph_data = "sequenceDiagram\n"
        graph_data += f"\tautonumber\n"
        for participant in self.participants.values():
            graph_data += f"\tparticipant {participant.id} as {participant.name}\n"
        for sequence_step in self.sequence_steps:
            if sequence_step.target_id is None:
                graph_data += f"\t{sequence_step.source_id} -->> {sequence_step.source_id}: {sequence_step.description}\n"
            else:
                graph_data += f"\t{sequence_step.source_id} ->> {sequence_step.target_id}: {sequence_step.description}\n"
        return graph_data


class MermaidDiagram:
    def __init__(self, name):
        self.name = name
        self.nodes = {}
        self.links = []

    def add_node(self, id, name, parent_id=None):
        # Sanitize ID and Name for mermaid
        safe_id = "".join(c for c in id if c.isalnum() or c in ('_',))
        # Escape quotes in name
        safe_name = name.replace('"', '&quot;')
        self.nodes[id] = {
            "id": safe_id, 
            "name": safe_name, 
            "parent": parent_id,
            "children": []
        }

    def add_link(self, source_id, target_id, label=None):
        self.links.append({"source": source_id, "target": target_id, "label": label})

    def generate(self):
        # Pre-process nesting only for generation
        # Reset children to avoid duplicates if generated multiple times
        for node in self.nodes.values():
            node["children"] = []

        roots = []
        for node_id, node in self.nodes.items():
            if node["parent"] and node["parent"] in self.nodes:
                self.nodes[node["parent"]]["children"].append(node)
            else:
                roots.append(node)

        graph_data = "flowchart TD\n"
        
        def render_node(node, indent=1):
            s = ""
            tab = "\t" * indent
            if node["children"]:
                s += f"{tab}subgraph {node['id']} [\"{node['name']}\"]\n"
                for child in node["children"]:
                    s += render_node(child, indent + 1)
                s += f"{tab}end\n"
            else:
                s += f"{tab}{node['id']}[\"{node['name']}\"]\n"
            return s

        for root in roots:
            graph_data += render_node(root)
            
        for link in self.links:
            source = self.nodes.get(link['source'])
            target = self.nodes.get(link['target'])
            if source and target:
                arrow = "-->"
                if link['label']:
                    graph_data += f"\t{source['id']} {arrow}|{link['label']}| {target['id']}\n"
                else:
                    graph_data += f"\t{source['id']} {arrow} {target['id']}\n"
        return graph_data


model_objects = {}
# Cache diagrams by diagram_id instead of object_id to avoid redundant fetches
diagram_cache = {}


def get_model_object(model_object_id):
    if model_object_id in model_objects:
        return model_objects[model_object_id]
    
    # Check if model_object_id is None to avoid unnecessary 404s
    if model_object_id is None:
        return {"id": None, "name": "Unknown", "type": "unknown"}

    rmodel = requests.get(
        f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/model/objects/{model_object_id}",
        headers=headers)
    model_object = rmodel.json()
    if "modelObject" in model_object:
        model_object = model_object["modelObject"]
    elif "id" not in model_object:
        # If we got a 404 or unexpected response that doesn't look like a model object
        print(f"Warning: Failed to fetch model object {model_object_id}. Response: {model_object}")
        # Create a dummy object to allow continuity
        model_object = {"id": model_object_id, "name": "Unknown Model Object", "type": "unknown"}
    
    model_objects[model_object_id] = model_object
    return model_object



def get_diagram_data(diagram_id):
    # Check cache by diagram_id first
    if diagram_id in diagram_cache:
        return diagram_cache[diagram_id]
        
    print(f"Fetching diagram [{diagram_id}] from API")
    url = f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/diagrams/{diagram_id}"
    
    # 1. Fetch main Diagram Metadata
    rdia = requests.get(url, headers=headers)
    if rdia.status_code != 200:
        print(f"Error fetching diagram: {rdia.status_code}")
        return None
    
    response_json = rdia.json()
    dia = response_json.get("diagram", {})
    
    # 2. Strategy: Attempt to find 'objects' and 'relationships' map
    objects = dia.get("objects")
    relationships = dia.get("relationships", [])
    
    if not objects and "diagramContent" in response_json:
        objects = response_json["diagramContent"].get("objects")
    if not relationships and "diagramContent" in response_json:
        relationships = response_json["diagramContent"].get("relationships")
    
    if not objects or not relationships:
        sub_resources = {
            "/content": ["diagramContent", "objects"], 
            "/objects": ["objects"],                   
            "/elements": ["elements"],
            "/relationships": ["relationships"]
        }

        for suffix, keys in sub_resources.items():
            print(f"DEBUG: Fetching sub-resource {suffix}")
            r_sub = requests.get(f"{url}{suffix}", headers=headers)
            if r_sub.status_code == 200:
                data = r_sub.json()
                
                # Check for relationships in common locations
                if not relationships:
                     if "diagramContent" in data and isinstance(data["diagramContent"], dict):
                         relationships = data["diagramContent"].get("relationships", [])
                         if relationships: print(f"DEBUG: Found {len(relationships)} relationships in diagramContent")
                         else: print(f"DEBUG: diagramContent present but no relationships")
                     elif "relationships" in data:
                         relationships = data["relationships"]
                         if relationships: print(f"DEBUG: Found {len(relationships)} relationships in root")
                     elif isinstance(data, list):
                         # Maybe the response IS the list of relationships? (unlikely for objects but possible for specific endpoints)
                         pass
                     else:
                         print(f"DEBUG: No relationships found in root or diagramContent for {suffix}")
                 
                if suffix == "/relationships":
                    # Specific handling if we added a new endpoint guess
                    if isinstance(data, list):
                        relationships = data
                    elif isinstance(data, dict):
                         if "relationships" in data:
                             relationships = data["relationships"]
                         else:
                             # Maybe the dict values are relationships?
                             pass

                temp_obj = data
                valid_path = True
                
                # Logic to drill down to objects
                for key in keys:
                    if isinstance(temp_obj, dict) and key in temp_obj:
                        temp_obj = temp_obj[key]
                    elif isinstance(temp_obj, dict) and key == "objects" and "objects" not in temp_obj:
                            pass 
                    else:
                        valid_path = False
                        break
                
                if valid_path and isinstance(temp_obj, dict) and temp_obj:
                    if not objects:
                        objects = temp_obj
                
                if suffix == "/objects" and not objects and isinstance(data, dict):
                        objects = data
                        if not relationships and "relationships" in data:
                            relationships = data["relationships"]
                
                if objects and relationships:
                    break
    
    # Final cleanup of relationships to ensure it's a list
    if relationships and isinstance(relationships, dict):
        relationships = list(relationships.values())

    if objects is None:
        print(f"Warning: Could not locate diagram objects for {diagram_id}")
        dia["objects"] = {}
    else:
        dia["objects"] = objects
        
    if not relationships:
        dia["relationships"] = []
    else:
        dia["relationships"] = relationships
            
    return dia


def get_diagram_object(diagram_id, object_id):
    if object_id is None:
        return None

    dia = get_diagram_data(diagram_id)
    if not dia:
        return None

    # Look up object in diagram
    if object_id not in dia["objects"]:
        # Only print error once per object miss if verbose, but standard logging is fine
        print(f"Error: Object {object_id} not found in diagram {diagram_id}")
        return None 

    return dia["objects"][object_id]



def find_flow_by_name(name):
    """
    For given flow name finds its id
    :param name:
    :return:
    """
    rflow = requests.get(
        f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/flows",
        headers=headers)

    # {{baseUrl}}/landscapes/:landscapeId/versions/:versionId/flows/:flowId
    flows = rflow.json()["flows"]
    for flow in flows:
        if flow["name"] == name:
            return flow["id"]
    return None


def find_diagram_by_name(name):
    """
    For given diagram name finds its id
    :param name:
    :return:
    """
    rdiagrams = requests.get(
        f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/diagrams",
        headers=headers)
    
    if rdiagrams.status_code != 200:
        return None

    diagrams = rdiagrams.json().get("diagrams", [])
    for d in diagrams:
        if d["name"] == name:
            return d["id"]
    return None


def create_file_name(filename, extension):
    keepcharacters = (' ', '.', '_')
    safe_filename = "".join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()
    return f"{safe_filename}.{extension}"


def main(flow_name: Optional[str] = typer.Option(None, help="The name of the flow to create sequence diagram for"),
         diagram_name: Optional[str] = typer.Option(None, "--diagram-name", "-D", help="The name of the full diagram to convert"),
         export_type: MermaidExportType = MermaidExportType.png,
         convert: bool = typer.Option(False, "--convert", "-c",
                                      help="Converts the generated sequence to supported output format. Requires MMDC_CMD environment variable to be set to the path of mermaid executable"),
         data_dir: Path = typer.Option("data/", "--data-dir", "-d",
                                       help="Path where to store the generated sequence diagram"),
         ):
    
    if diagram_name:
        dia_id = find_diagram_by_name(diagram_name)
        if dia_id is None:
            typer.secho(f"Unable to find diagram [{diagram_name}]", fg=typer.colors.RED)
            return

        dia = get_diagram_data(dia_id)
        if not dia:
             typer.secho(f"Unable to fetch diagram data", fg=typer.colors.RED)
             return
        
        objects = dia.get("objects", {})
        relationships = dia.get("relationships", [])
             
        mdia = MermaidDiagram(diagram_name)
        
        # First pass: Build a map of diagram_id -> model_id
        dia_to_model = {}
        if objects:
             for obj_id, obj_data in objects.items():
                  if obj_data.get("modelId"):
                      dia_to_model[obj_id] = obj_data["modelId"]
                      
        print(f"DEBUG: Found {len(objects)} objects")
        
        # Strategy 3: if diagram relationships are empty, fetch ALL model connections and filter?
        # A bit inefficient but standard API seems to hide them for some reason
        if not relationships:
             print("DEBUG: Fetching all model connections as fallback strategy")
             r_conns = requests.get(
                f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/model/connections",
                headers=headers)
             if r_conns.status_code == 200:
                  all_conns = r_conns.json().get("modelConnections", [])
                  print(f"DEBUG: Found {len(all_conns)} total model connections")
                  
                  # Filter connections that are relevant to the objects in this diagram
                  diagram_model_ids = set(dia_to_model.values())
                  
                  # We need to map model relationship back to diagram relationship if possible, 
                  # or just draw the link between model objects if both exist in diagram.
                  
                  for conn in all_conns:
                       source_model = conn.get("originId") or conn.get("sourceId")
                       target_model = conn.get("targetId") or conn.get("destinationId")

                       if source_model in diagram_model_ids and target_model in diagram_model_ids:
                            # It's a candidate! But is it VISIBLE in this diagram?
                            # conn['diagrams'] might tell us?
                            # Documentation says "diagrams": {} 
                            dia_keys = conn.get("diagrams", {}).keys()
                            
                            # If diagram_id is in the keys, it's definitely in.
                            # Even if not, if both ends are in the diagram, it usually implies a connection in 
                            # C4 unless explicitly hidden.
                            
                            # Even if not, if both ends are in the diagram, it usually implies a connection in 
                            # C4 unless explicitly hidden.
                            if dia_id in dia_keys or (source_model in diagram_model_ids and target_model in diagram_model_ids):
                                 relationships.append({
                                      "sourceId": [k for k,v in dia_to_model.items() if v == source_model][0], # Reverse lookup, risky if duplicates
                                      "targetId": [k for k,v in dia_to_model.items() if v == target_model][0],
                                      "label": conn.get("name"),
                                      "modelId": conn.get("id")
                                 })
                  print(f"DEBUG: Deduced {len(relationships)} relationships from model connections")

        print(f"DEBUG: Found {len(relationships)} relationships")
        
        # DEBUG: if 0 relationships, maybe they are embedded in objects? (Links?)
        if len(relationships) == 0:
            print("DEBUG: Checking objects for embedded links/relationships...")
            for obj_id, obj_data in objects.items():
                # Inspect object structure for clues
                # print(f"DEBUG: Object {obj_id} keys: {obj_data.keys()}")
                pass

        # Parse nodes and hierarchy - ensure non-model parents (groups) are processed
        
        # Sort objects to potentially process parents (groups) before children if possible
        # Simple heuristic: objects without modelId are likely groups (0), models are (1)
        
        sorted_items = sorted(objects.items(), key=lambda item: 1 if item[1].get("modelId") else 0)

        for obj_id, obj_data in sorted_items:
             model_id = obj_data.get("modelId")
             parent_dia_id = obj_data.get("parentId")
             
             if model_id:
                 model_obj = get_model_object(model_id)
                 
                 # Resolve Parent (Diagram ID)
                 final_parent_id = parent_dia_id
                 
                 # Fallback: Check if the model object itself has a parent defined (Structural parent)
                 if not final_parent_id and "parentId" in model_obj:
                     p_struct = model_obj["parentId"]
                     # Find diagram ID for this model parent
                     candidates = [k for k,v in dia_to_model.items() if v == p_struct]
                     if candidates:
                         final_parent_id = candidates[0]

                 # Ensure parent exists if not yet added
                 if final_parent_id and final_parent_id not in mdia.nodes:
                      if final_parent_id in objects:
                           p_data = objects[final_parent_id]
                           p_name = p_data.get("name", "Group")
                           mdia.add_node(final_parent_id, p_name, p_data.get("parentId"))

                 # Use DIAGRAM ID as key
                 mdia.add_node(obj_id, model_obj["name"], final_parent_id)
             
             else:
                 # Logic for objects without modelId (e.g. pure Groups)
                 name = obj_data.get("name")
                 if not name:
                     if obj_data.get("type") == "boundary" or "style" in obj_data:
                         name = "Group"
                     else:
                         continue

                 parent_id = obj_data.get("parentId")
                 
                 # Just use the Diagram ID directly
                 if parent_id and parent_id not in mdia.nodes and parent_id in objects:
                      mdia.add_node(parent_id, objects[parent_id].get("name", "Group"), objects[parent_id].get("parentId"))

                 if obj_id not in mdia.nodes:
                     mdia.add_node(obj_id, name, parent_id)

        if isinstance(relationships, dict):
             relationships = relationships.values()
             
        for rel in relationships:
             source_id = rel.get("sourceId") 
             target_id = rel.get("targetId")
             
             label = rel.get("label") or rel.get("name")
             
             rel_model_id = rel.get("modelId")
             if not label and rel_model_id:
                  rel_model = get_model_object(rel_model_id)
                  label = rel_model.get("name")

             # Ensure both ends exist in the diagram objects
             if (source_id in objects or source_id in mdia.nodes) and (target_id in objects or target_id in mdia.nodes):
                 mdia.add_link(source_id, target_id, label)

        print(mdia.generate())
        
        os.makedirs(data_dir, exist_ok=True)
        filename = create_file_name(diagram_name, 'mmd')
        f = open(f"{data_dir}/{filename}", "w")
        f.write(mdia.generate())
        f.close()
        
        if convert:
            os.system(
            f"{environ['MMDC_CMD']} -p puppeteer-config.json -i \"{data_dir}/{filename}\" -o \"{data_dir}/{create_file_name(diagram_name, export_type.value)}\"")
        return

    if flow_name is None:
         typer.secho("Please provide --flow-name or --diagram-name", fg=typer.colors.RED)
         return

    flow_id = find_flow_by_name(flow_name)
    if flow_id is None:
        # TODO add debug info (e.g. http call info)
        typer.secho(f"Unable to find flow [{flow_name}]", fg=typer.colors.RED)
        return
    rflow = requests.get(
        f"https://api.icepanel.io/v1/landscapes/{landscape_id}/versions/{version_id}/flows/{flow_id}",
        headers=headers)

    # print(rflow.json())
    if rflow.status_code != 200 or "flow" not in rflow.json():
        typer.secho(f"Unable to find flow [{rflow.json()}]", fg=typer.colors.RED)
        return
    flow = rflow.json()["flow"]
    seq = MermaidSequence(flow["name"])
    steps = {k: v for k, v in sorted(flow["steps"].items(), key=lambda item: item[1]["index"])}

    for k, v in steps.items():
        dia_obj_ori = get_diagram_object(flow["diagramId"], v["originId"])
        if dia_obj_ori is None:
            print(f"Skipping step {k} because origin object {v['originId']} could not be found.")
            continue
            
        dia_obj_tar = get_diagram_object(flow["diagramId"], v["targetId"]) if v["targetId"] is not None else None
        
        model_obj_ori = get_model_object(dia_obj_ori["modelId"])
        model_obj_tar = None
        if dia_obj_tar is not None:
            model_obj_tar = get_model_object(dia_obj_tar["modelId"])
        participant_ori = SequenceParticipant(model_obj_ori["id"], model_obj_ori["name"])
        seq.add_participant(participant_ori)
        participant_tar = None
        if model_obj_tar is not None:
            participant_tar = SequenceParticipant(model_obj_tar["id"], model_obj_tar["name"])
            seq.add_participant(participant_tar)
        interaction = SequenceInteraction(v["id"], v["type"], v["description"], participant_ori.id,
                                          participant_tar.id if participant_tar is not None else None)
        # print(f"{k}: {v['description']} - {v['type']} - {model_obj_ori['name']}")
        seq.add_sequence_step(interaction)
    print(seq.generate())
    
    # Ensure data directory exists
    os.makedirs(data_dir, exist_ok=True)
    
    f = open(f"{data_dir}/{create_file_name(flow_name, 'mmd')}", "w")
    f.write(seq.generate())
    f.close()
    if convert:
        os.system(
            f"{environ['MMDC_CMD']} -p puppeteer-config.json -i \"{data_dir}/{create_file_name(flow_name, 'mmd')}\" -o \"{data_dir}/{create_file_name(flow_name, export_type.value)}\"")  # -b transparent


# Press the green button in the gutter to run the script.
if __name__ == "__main__":
    typer.run(main)
