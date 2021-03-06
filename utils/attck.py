import json
import aiohttp
import asyncio
from environment import config
from reternalapi import ReternalAPI

def load_magma(path=config['MAGMA_PATH']):
    magma_mapping = { }
    with open(path, 'r') as magma_file:
        json_object = json.loads(magma_file.read())
        for mapping in json_object:
            magma_mapping[mapping['external_id']] = mapping
    return magma_mapping


class Technique:
    def __init__(self, technique):
        self.technique = technique

    @classmethod
    def from_cti(cls, technique):
        ''' Format technique to match expected API schema '''
        technique = { 
            'technique_id': technique['id'],
            'name':technique['name'],
            'description': technique['description'],
            'platforms': technique['x_mitre_platforms'], 
            'permissions_required': technique.get('x_mitre_permissions_required', []),
            'data_sources': technique.get('x_mitre_data_sources', []),
            'references': technique['external_references'],
            'kill_chain_phases': [phase['phase_name'] for phase in technique['kill_chain_phases']],
            'is_subtechnique': technique.get('x_mitre_is_subtechnique', False),
            'data_sources_available': [],
            'actors': []
        }
        return cls(technique)

    def set_magma(self, magma_mapping):
        external_id = self.technique['external_references'][0]['external_id']
        if external_id in self.magma_mapping:
            mapped_usecase = self.magma_mapping[external_id]
            mapped_usecase.pop('external_id')
            self.technique['magma'] = mapped_usecase


class Actor:
    def __init__(self, actor):
        self.actor = actor

    @classmethod
    def from_cti(cls, actor):
        actor = {
            'actor_id': actor['id'], 
            'name': actor['name'],
            'references': actor['external_references'],
            'aliases': actor.get('aliases', None),
            'description': actor.get('description', None),
            'techniques': []
        }
        return cls(actor)


class MitreAttck:
    def __init__(self, actors = None, techniques = None):
        self.actors = actors
        self.techniques = techniques

    @staticmethod
    def __make_related(actors, techniques, relationships):
        ''' Denormalize relationship between actors and techniques '''
        for relationship in relationships:
            related_technique = techniques.get(relationship['target_ref'], None)
            related_actor = actors.get(relationship['source_ref'], None)
            if related_actor and related_technique:
                related_technique.technique['actors'].append({
                    'actor_id': related_actor.actor['actor_id'],
                    'name': related_actor.actor['name']
                })
                related_actor.actor['techniques'].append({
                    'technique_id': related_technique.technique['technique_id'],
                    'name': related_technique.technique['name']
                })
        return actors, techniques

    @classmethod
    async def from_cti(cls, cti_url='https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json'):
        # Since github does not return a valid json response header
        # we have to load the response as text first and parse afterwards
        async with aiohttp.ClientSession() as session:
            async with session.get(cti_url) as resp:
                get_entries = await resp.text()

        actors, techniques, relationships = {}, {}, []
        for entry in json.loads(get_entries)['objects']:
            if entry.get('revoked', False) == False:
                if entry['type'] == 'attack-pattern':
                    techniques[entry['id']] = Technique.from_cti(entry)
                elif entry['type'] == 'intrusion-set':
                    actors[entry['id']] = Actor.from_cti(entry)
                elif entry['type'] == 'relationship':
                    relationships.append(entry)

        actors, techniques = cls.__make_related(actors, techniques, relationships)
        return cls(actors, techniques)


async def import_attck(*args, **kwargs):
    ''' Retrieve MITRE ATTCK database and format data '''
    mitre_attck = await MitreAttck.from_cti(config['CTI_URL'])
    async with ReternalAPI(api_url=config['API_URL'], api_token=config['API_TOKEN']) as reternal:
        for technique in mitre_attck.techniques.values():
            await reternal.save('/mitre/techniques', technique.technique)

        for actor in mitre_attck.actors.values():
            await reternal.save('/mitre/actors', actor.actor)

if __name__ == "__main__":
    asyncio.run(import_attck())
